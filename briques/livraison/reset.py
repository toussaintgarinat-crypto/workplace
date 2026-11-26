"""Reset bleu/vert d'une application (S247 2b) : deux emplacements permanents, A (l'app
d'origine) et B (son jumeau). Le reset travaille toujours sur l'emplacement INACTIF (base neuve
restaurée, variables repointées, redéploiement, santé, recomptage) puis échange les hôtes des
deux domaines. Fail closed : toute défaillance avant l'échange laisse l'actif inchangé.

Ni `reset` ni `retour_arriere` ne lèvent (sauf `CancelledError`, relancée après compensation) :
toute issue passe par `operations.terminer`, avec un motif FIXE (jamais un message d'exception,
jamais une valeur d'environnement). Les journaux ne portent que des motifs et des noms d'étape.
"""
import asyncio
import copy
import logging
import os
import re
import secrets
import time
from typing import Awaitable, Callable, Optional

import httpx

import operations
from client_executeur import ExecuteurErreur
from dokploy import CLES_SOURCE, DokployErreur, peut_etre_appliquee
from envreecriture import nomme_la_base, reecrire_env
from sauvegarde import TOLERANCE_HORLOGE_S, _epoch

log = logging.getLogger(__name__)
ESSAIS_MAX = 3
SANTE_ESSAIS, SANTE_PAS_S, SANTE_DELAI_S = 3, 5.0, 10.0
CONFIRMATION_ESSAIS, CONFIRMATION_PAS_S = 60, 5.0
SUFFIXE_JUMEAU = "-jumeau"
RE_GENEREE = re.compile(r"[a-z_][a-z0-9_]{0,30}_v[0-9a-f]{8}")
RE_RACINE = re.compile(r"[a-z_][a-z0-9_]{0,30}")    # racine dont le nom généré reste supprimable
Sante = Callable[[str, str], Awaitable[bool]]


class _Echec(Exception):
    def __init__(self, motif: str):
        super().__init__(motif)
        self.motif = motif


def _motif(e: BaseException) -> str:
    """Le SEUL endroit qui traduit une exception en motif."""
    if isinstance(e, _Echec):
        return e.motif
    if isinstance(e, DokployErreur):
        return "erreur_dokploy"
    if isinstance(e, ExecuteurErreur):
        return "erreur_executeur"
    if isinstance(e, (OSError, operations.OperationInconnue)):
        return "erreur_disque"
    return "erreur_interne"


def base_effective(entree: dict, etat: Optional[dict]) -> dict:
    """Entrée d'inventaire dont la base suit la base ACTIVE après un reset."""
    e = copy.deepcopy(entree)
    if isinstance(etat, dict) and etat.get("base_active") and e.get("bases"):
        e["bases"][0]["base"] = etat["base_active"]
    return e


def peut_retour_arriere(etat: Optional[dict]) -> bool:
    if not isinstance(etat, dict):
        return False
    emp = etat.get("emplacements") or {}
    return bool(etat.get("actif") in ("A", "B") and etat.get("base_active")
                and etat.get("base_precedente") and not etat.get("retour_invalide")
                and isinstance(emp.get("A"), dict) and isinstance(emp.get("B"), dict))


async def sante_http(hote: str, chemin: str, dormir: Callable = asyncio.sleep,
                     transport: Optional[httpx.AsyncBaseTransport] = None) -> bool:
    """GET via Traefik avec l'en-tête Host ; 2xx/3xx = sain. Sans URL configurée : non sain."""
    base = os.getenv("LIVRAISON_TRAEFIK_URL")
    if not base:
        return False
    for i in range(SANTE_ESSAIS):
        if i:
            await dormir(SANTE_PAS_S)
        try:
            async with httpx.AsyncClient(transport=transport, timeout=SANTE_DELAI_S) as cl:
                r = await cl.get(base.rstrip("/") + chemin, headers={"Host": hote})
            if 200 <= r.status_code < 400:
                return True
        except httpx.HTTPError:
            pass
    return False


class _Contexte:
    def __init__(self, d, ex, app_nom, operation_id, sante, horloge, dormir):
        self.d, self.ex, self.app, self.op = d, ex, app_nom, operation_id
        self.sante = sante or (lambda h, ch: sante_http(h, ch, dormir=dormir))
        self.horloge, self.dormir = horloge, dormir
        self.etape: Optional[str] = None
        self.nouvelle: Optional[str] = None     # base générée peut-être créée, pas encore active
        self.rebase_tente = self.bascule_tentee = self.bascule_faite = False
        self.env_ecrit = False          # env de l'inactif peut-être réécrit (retour invalide)
        self.public_bascule = False     # le public sert peut-être déjà l'inactif
        self.bascule_incertaine = False  # 1er échange peut-être appliqué (réponse perdue/5xx)
        self.precedente_protegee = False  # base précédente = écritures d'une instance quittée
        self.conserve = False           # base neuve et sauvegarde gardées en l'état
        self.cible_sauvegarde: Optional[str] = None
        self.base_active: Optional[str] = None
        self.alertes: list[str] = []

    def charger(self, entree) -> None:
        if not isinstance(entree, dict) or not entree.get("bases") or not entree.get("reset"):
            raise _Echec("configuration_manquante")
        b = entree["bases"][0]
        self.service, self.utilisateur = b["service"], b["utilisateur"]
        self.sauvegarde_id, self.prefixe, self.base_racine = (b["sauvegarde_id"],
                                                              b["prefixe_s3"], b["base"])
        # Une racine hors motif donnerait des bases générées jamais supprimables ; une racine
        # déjà « générée » trahit une entrée effective (base_effective) au lieu de l'entrée brute.
        if (not isinstance(self.base_racine, str) or not RE_RACINE.fullmatch(self.base_racine)
                or RE_GENEREE.fullmatch(self.base_racine)):
            raise _Echec("configuration_manquante")
        self.cfg = entree["reset"]

    def marquer(self, nom: str, **extra) -> None:
        self.etape = nom
        log.info("reset %s : étape %s", self.app, nom)
        operations.etape(self.app, self.op, nom, **extra)

    def lire_etat(self, etat: dict) -> None:
        self.emp, self.actif = etat.get("emplacements") or {}, etat.get("actif")
        if self.actif not in ("A", "B") or not all(
                isinstance(self.emp.get(k), dict) and self.emp[k].get("app_id")
                and self.emp[k].get("domaine_id") for k in "AB"):
            raise _Echec("configuration_manquante")
        self.inactif = "B" if self.actif == "A" else "A"
        self.base_active = etat.get("base_active") or self.base_racine
        self.base_precedente = etat.get("base_precedente")
        self.precedente_protegee = operations.precedente_protegee(etat)

    def dom(self, slot: str) -> str:
        return self.emp[slot]["domaine_id"]

    def app_id(self, slot: str) -> str:
        return self.emp[slot]["app_id"]


# ── étape 1 : préparation ──

async def _domaine(c: _Contexte, app_id: str, domaines: list, hote: str) -> str:
    """Aucun domaine : on le crée. Exactement un, sur l'hôte attendu : on le garde. Sinon on
    refuse (un alias non échangé resterait sur l'ancienne instance)."""
    if not domaines:
        return await c.d.creer_domaine(app_id, hote, c.cfg["port_app"])
    if len(domaines) != 1 or domaines[0].get("host") != hote:
        raise _Echec("configuration_manquante")
    return domaines[0]["domainId"]


async def _provisionner(c: _Contexte, app_id: str) -> None:
    a = await c.d.app_complete(app_id)
    dom_a = await _domaine(c, app_id, a.get("domains") or [], c.cfg["domaine_public"])
    nom_b = c.app + SUFFIXE_JUMEAU
    jumeaux = [x for x in await c.d.apps() if x.get("nom") == nom_b]
    if len(jumeaux) > 1:
        raise _Echec("configuration_manquante")
    if jumeaux:     # provisionnement précédent interrompu après la création
        b_id = jumeaux[0]["id"]
        doms_b = (await c.d.app_complete(b_id)).get("domains") or []
    else:
        b_id = (await c.d.creer_app(await c.d.environnement_id(), nom_b,
                                    "Jumeau bleu/vert géré par la brique livraison"))["id"]
        doms_b = []
    dom_b = await _domaine(c, b_id, doms_b, c.cfg["domaine_test"])
    operations.enregistrer_emplacements(c.app, {"app_id": app_id, "domaine_id": dom_a},
                                        {"app_id": b_id, "domaine_id": dom_b}, "A", c.base_racine)


async def _verifier_hotes(c: _Contexte) -> None:
    """L'actif sert le public, l'inactif le test : sinon une bascule précédente est restée
    incomplète et on ne touche à rien."""
    for slot, hote in ((c.actif, c.cfg["domaine_public"]), (c.inactif, c.cfg["domaine_test"])):
        doms = [x for x in (await c.d.app_complete(c.app_id(slot))).get("domains") or []
                if x.get("domainId") == c.dom(slot)]
        if len(doms) != 1 or doms[0].get("host") != hote:
            raise _Echec("configuration_manquante")


async def _preparer(c: _Contexte, app_id: str) -> None:
    c.marquer("preparation")
    if not (operations.lire(c.app) or {}).get("emplacements"):
        await _provisionner(c, app_id)
    c.lire_etat(operations.lire(c.app) or {})
    if c.app_id("A") != app_id:
        raise _Echec("configuration_manquante")
    await _verifier_hotes(c)
    # Contrôles purs, AVANT tout clonage : l'actif lit bien la base active (sinon la réécriture
    # échouerait après un clonage inutile), et la sauvegarde Dokploy vise bien cette base (sinon
    # le clone partirait d'une autre base sans que personne ne le voie). L'env ne sort pas d'ici.
    actif = await c.d.app_complete(c.app_id(c.actif))
    if not nomme_la_base(actif.get("env"), c.cfg["variable_env"], c.base_active):
        raise _Echec("env_sans_variable_base")
    if await c.d.base_sauvegarde(c.sauvegarde_id) != c.base_active:
        raise _Echec("sauvegarde_desynchronisee")


# ── étapes 2 à 5 : clonage, configuration, santé, recomptage ──

async def _cloner(c: _Contexte) -> None:
    debut = c.horloge()
    await c.d.sauvegarder_base(c.sauvegarde_id)
    fichiers = await c.d.fichiers_sauvegarde(c.sauvegarde_id)
    if not fichiers or _epoch(fichiers[0]["date"]) < debut - TOLERANCE_HORLOGE_S:
        raise _Echec("sauvegarde_absente")
    c.heure_sauvegarde = (fichiers[0]["date"] or "")[11:19]
    nom = f"{c.base_racine}_v{secrets.token_hex(4)}"
    # Persisté AVANT de cloner : après un arrêt brutal, une base orpheline reste identifiable.
    operations.etape(c.app, c.op, "clonage", base_neuve=nom)
    c.nouvelle = nom
    r = await c.ex.cloner(c.service, c.utilisateur, c.base_active,
                          f"{c.prefixe}/{fichiers[0]['nom']}", c.nouvelle)
    c.comptages = r.get("comptages_origine")
    if (r.get("verdict") != "valide" or r.get("nouvelle_base") != c.nouvelle
            or not isinstance(c.comptages, dict)):
        raise _Echec("clonage_invalide")


async def _dernier_deploiement(c: _Contexte, id_: str) -> Optional[dict]:
    deps = (await c.d.app(id_)).get("deploiements") or []
    return deps[0] if deps else None


async def _cause_deploiement(c: _Contexte, id_: str, e: DokployErreur) -> str:
    if e.statut == 504:
        return "deploiement_incertain"
    try:
        statut = (await c.d.app_complete(id_)).get("applicationStatus")
    except DokployErreur:
        return "deploiement_incertain"
    return "deploiement_echoue" if statut == "error" else "deploiement_incertain"


async def _confirmer_deploiement(c: _Contexte, id_: str, avant: Optional[dict]) -> None:
    """Un REdéploiement peut lire un `done` ancien : on exige un déploiement NOUVEAU terminé."""
    for i in range(CONFIRMATION_ESSAIS):
        if i:
            await c.dormir(CONFIRMATION_PAS_S)
        try:
            dep = await _dernier_deploiement(c, id_)
        except DokployErreur:
            continue
        if dep and (avant is None or dep.get("id") != avant.get("id")):
            if dep.get("statut") == "done":
                return
            if dep.get("statut") == "error":
                raise _Echec("deploiement_echoue")
    raise _Echec("deploiement_incertain")


async def _configurer(c: _Contexte) -> None:
    actif = await c.d.app_complete(c.app_id(c.actif))
    try:
        env = reecrire_env(actif.get("env") or "", c.cfg["variable_env"], c.base_active,
                           c.nouvelle)
    except ValueError:
        raise _Echec("env_inattendu") from None
    source = {k: actif.get(k) for k in CLES_SOURCE}
    if any(v is None for v in source.values()):
        raise _Echec("configuration_manquante")
    id_ = c.app_id(c.inactif)
    c.env_ecrit = True      # avant l'appel : un délai dépassé peut l'avoir appliqué
    await c.d.ecrire_env(id_, env)
    await c.d.configurer_source(id_, source)
    avant = await _dernier_deploiement(c, id_)
    try:
        await c.d.deployer_et_attendre(id_, "reset bleu/vert", dormir=c.dormir)
    except DokployErreur as e:
        raise _Echec(await _cause_deploiement(c, id_, e)) from None
    await _confirmer_deploiement(c, id_, avant)


async def _verifier_sante(c: _Contexte) -> None:
    try:
        sain = await c.sante(c.cfg["domaine_test"], c.cfg["sante_chemin"])
    except Exception:
        sain = False
    if sain is not True:
        raise _Echec("sante_ko")


async def _supprimer(c: _Contexte, base: Optional[str], proteger: set) -> bool:
    """Supprime une base GÉNÉRÉE (jamais une base d'origine ni une base en service).
    Meilleur effort : False si l'exécuteur a échoué."""
    if not base or not RE_GENEREE.fullmatch(base) or base in proteger | {c.base_racine}:
        return True
    try:
        await c.ex.supprimer_base(c.service, c.utilisateur, base)
        return True
    except Exception as e:
        log.warning("reset %s : suppression d'une base générée impossible (%s)", c.app, _motif(e))
        return False


async def _abandonner_nouvelle(c: _Contexte) -> None:
    if c.nouvelle and not await _supprimer(c, c.nouvelle, {c.base_active, c.base_precedente}):
        c.alertes.append("base neuve non supprimée")
    c.nouvelle = None


async def _preparer_inactif(c: _Contexte) -> None:
    for essai in range(1, ESSAIS_MAX + 1):
        c.marquer("clonage", essais=essai)
        await _cloner(c)
        c.marquer("configuration")
        await _configurer(c)
        c.marquer("sante")
        await _verifier_sante(c)
        c.marquer("recomptage")
        r = await c.ex.comptages(c.service, c.utilisateur, c.base_active)
        if r.get("comptages") == c.comptages:
            return
        log.info("reset %s : écritures pendant l'opération, essai %d", c.app, essai)
        await _abandonner_nouvelle(c)
    raise _Echec("ecritures_en_cours")


# ── étapes 6 et 7 : sauvegarde, bascule ──

async def _rebaser(c: _Contexte, base: str) -> None:
    c.marquer("sauvegarde")
    c.rebase_tente = True
    c.cible_sauvegarde = base
    try:
        await c.d.rebaser_sauvegarde(c.sauvegarde_id, base)
    except DokployErreur as e:
        if not peut_etre_appliquee(e):      # provablement non appliqué : rien à défaire
            c.rebase_tente = False
            c.cible_sauvegarde = None
        raise


async def _basculer(c: _Contexte, base_active: str, base_precedente: Optional[str],
                    precedente_protegee: bool = False) -> None:
    """Public sur l'inactif D'ABORD, puis test sur l'ancien actif : jamais sans hôte public."""
    c.marquer("bascule")
    c.bascule_tentee = True
    port = c.cfg["port_app"]
    try:
        await c.d.changer_hote(c.dom(c.inactif), c.cfg["domaine_public"], port)
    except DokployErreur as e:
        # Requête partie sans réponse fiable (coupure, délai, 5xx) : peut-être appliquée, et
        # Dokploy peut encore l'appliquer après notre remise des hôtes.
        if peut_etre_appliquee(e):
            c.public_bascule = c.bascule_incertaine = True
        raise
    except asyncio.CancelledError:
        c.public_bascule = c.bascule_incertaine = True
        raise
    c.public_bascule = True     # de vrais utilisateurs écrivent peut-être déjà dans la base neuve
    await c.d.changer_hote(c.dom(c.actif), c.cfg["domaine_test"], port)
    operations.basculer_etat(c.app, c.inactif, base_active, base_precedente,
                             precedente_protegee=precedente_protegee)
    c.bascule_faite = True


async def _remettre_hotes(c: _Contexte) -> bool:
    ok = True
    port = c.cfg["port_app"]
    for slot, hote in ((c.actif, c.cfg["domaine_public"]), (c.inactif, c.cfg["domaine_test"])):
        try:
            await c.d.changer_hote(c.dom(slot), hote, port)
        except Exception:
            ok = False
    return ok


async def _compenser(c: _Contexte, motif: str) -> str:
    """Remet tout dans l'état d'avant (meilleur effort, ne lève jamais) ; rend le motif final.
    Dès que le public a pu servir l'inactif, la base neuve est GARDÉE (des données y ont
    peut-être été écrites). Hôtes remis avec certitude : la sauvegarde revient sur la base
    active de l'état (sinon le reset suivant clonerait la mauvaise base). Hôtes non remis, ou
    premier échange incertain (Dokploy peut encore l'appliquer) : la sauvegarde reste aussi
    sur la base neuve, et le message le dit."""
    if c.env_ecrit and not c.bascule_faite:
        try:
            operations.invalider_retour(c.app)
        except Exception as e:
            log.error("reset %s : retour arrière non invalidé (%s)", c.app, _motif(e))
    if c.bascule_tentee and not c.bascule_faite:
        remis = await _remettre_hotes(c)
        if c.bascule_incertaine or not remis:
            log.error("reset %s : bascule incomplète (hôtes %s), base neuve et sauvegarde "
                      "conservées — vérifier les domaines", c.app,
                      "remis" if remis else "non remis")
            c.conserve = True
            return "bascule_incomplete"
        if c.public_bascule:
            c.conserve = True
            if c.rebase_tente:
                try:
                    await c.d.rebaser_sauvegarde(c.sauvegarde_id, c.base_active)
                    c.cible_sauvegarde = c.base_active
                except Exception:
                    log.error("reset %s : sauvegarde non rebasculée sur la base active", c.app)
            log.error("reset %s : bascule incomplète (hôtes remis), base neuve conservée — "
                      "vérifier les domaines", c.app)
            return "bascule_incomplete"
        motif = "bascule_incomplete"
    if c.rebase_tente:
        try:
            await c.d.rebaser_sauvegarde(c.sauvegarde_id, c.base_active)
        except Exception:
            log.error("reset %s : sauvegarde non rebasculée sur la base active", c.app)
            motif = "sauvegarde_non_rebasee"
    try:
        await _abandonner_nouvelle(c)
    except Exception:
        pass
    return motif


def _terminer(c: _Contexte, etat: str, message: str, motif: Optional[str] = None) -> None:
    try:
        if motif:
            operations.etape(c.app, c.op, c.etape or "preparation", motif=motif)
        operations.terminer(c.app, c.op, etat, message)
    except Exception as e:
        log.warning("reset %s : état final non enregistré (%s)", c.app, _motif(e))


def _message_echec(c: _Contexte, motif: str) -> str:
    """Les noms de base ne sont pas des secrets (motif validé) : on les donne pour agir."""
    if motif == "env_sans_variable_base":
        return (f"env_sans_variable_base : ajoute {c.cfg['variable_env']} pointant sur la base "
                f"{c.base_active} dans l'application (instance {c.actif})")
    if motif == "sauvegarde_desynchronisee":
        return (f"sauvegarde_desynchronisee : la sauvegarde Dokploy ne vise pas la base active "
                f"{c.base_active} (bascule incomplète ?) : vérifier les domaines et la remettre "
                f"sur {c.base_active}")
    if motif != "bascule_incomplete":
        return motif
    parties = ["bascule_incomplete : vérifier les domaines"]
    if c.conserve:
        if c.cible_sauvegarde:
            parties.append(f"sauvegarde sur {c.cible_sauvegarde}")
        if c.nouvelle:
            parties.append(f"base neuve {c.nouvelle} conservée")
        if c.cible_sauvegarde and c.base_active and c.cible_sauvegarde != c.base_active:
            parties.append(f"l'état indique encore la base {c.base_active}")
    return " ; ".join(parties)


async def _executer(c: _Contexte, deroule) -> None:
    try:
        await deroule()
    except asyncio.CancelledError:
        if c.bascule_faite:     # bascule enregistrée : on ne la défait pas
            _terminer(c, "interrompue", "interrompue_par_arret : bascule faite, nettoyage "
                      "non fait", "interrompue_par_arret")
        else:
            await _compenser(c, "interrompue_par_arret")
            message = "interrompue_par_arret"
            if c.conserve:
                message += " ; " + _message_echec(c, "bascule_incomplete")
            _terminer(c, "interrompue", message, "interrompue_par_arret")
        raise
    except Exception as e:
        motif = await _compenser(c, _motif(e))
        log.warning("reset %s : échec à l'étape %s (%s)", c.app, c.etape, motif)
        _terminer(c, "echec", _message_echec(c, motif), motif)


# ── points d'entrée ──

def _resume(comptages: dict) -> str:
    lignes = sum(v for v in comptages.values() if isinstance(v, int) and not isinstance(v, bool))
    return f"{len(comptages)} tables, {lignes} lignes"


async def reset(d, ex, entree, app_nom: str, app_id: str, operation_id: str,
                sante: Optional[Sante] = None, horloge: Callable[[], float] = time.time,
                dormir: Callable = asyncio.sleep) -> None:
    """IMPORTANT : `entree` est l'entrée BRUTE de `inventaire.lire()`, JAMAIS celle de
    `main._entree_inventaire` / `base_effective` (sa base serait la génération active, refusée
    en `configuration_manquante`). La base active vient de l'état des opérations."""
    c = _Contexte(d, ex, app_nom, operation_id, sante, horloge, dormir)

    async def deroule() -> None:
        c.charger(entree)
        await _preparer(c, app_id)
        await _preparer_inactif(c)
        await _rebaser(c, c.nouvelle)
        ancienne, n_moins_2 = c.base_active, c.base_precedente
        await _basculer(c, c.nouvelle, ancienne)
        # Bascule faite et enregistrée : plus rien ne doit la défaire.
        try:
            c.marquer("nettoyage")
        except Exception:
            pass
        if (c.precedente_protegee and n_moins_2 and RE_GENEREE.fullmatch(n_moins_2)
                and n_moins_2 not in {c.nouvelle, ancienne, c.base_racine}):
            # Après un retour arrière, la « N-2 » est la base de l'instance quittée : elle
            # porte les écritures les plus récentes. Jamais supprimée automatiquement.
            c.alertes.append(f"base {n_moins_2} conservée (écritures de l'instance quittée) : "
                             "à supprimer à la main")
        elif not await _supprimer(c, n_moins_2, {c.nouvelle, ancienne}):
            c.alertes.append("ancienne base N-2 non supprimée (à nettoyer)")
        message = (f"Les données écrites dans l'ancienne instance après {c.heure_sauvegarde} "
                   f"(UTC, heure de la sauvegarde) restent dans l'ancienne base {ancienne}. "
                   f"L'instance {c.inactif} est active, base {c.nouvelle} "
                   f"({_resume(c.comptages)}).")
        if c.alertes:
            alerte = "Attention : " + " ; ".join(c.alertes) + "."
            # Le message est borné (operations.MESSAGE_MAX) : une alerte à agir ne doit jamais
            # être celle que la troncature coupe.
            message = (message + " " + alerte if len(message) + 1 + len(alerte)
                       <= operations.MESSAGE_MAX else alerte + " " + message)
        _terminer(c, "reussie", message)

    await _executer(c, deroule)


async def retour_arriere(d, entree, app_nom: str, operation_id: str,
                         sante: Optional[Sante] = None, horloge: Callable[[], float] = time.time,
                         dormir: Callable = asyncio.sleep) -> None:
    """Rebascule vers l'emplacement quitté et sa base (aucune base créée ni supprimée)."""
    c = _Contexte(d, None, app_nom, operation_id, sante, horloge, dormir)

    async def deroule() -> None:
        c.charger(entree)
        c.marquer("preparation")
        etat = operations.lire(app_nom)
        if isinstance(etat, dict) and etat.get("retour_invalide"):
            raise _Echec("retour_invalide")
        if not peut_retour_arriere(etat):
            raise _Echec("aucun_retour_possible")
        c.lire_etat(etat)
        await _verifier_hotes(c)
        # Défense en profondeur (le drapeau a pu ne pas s'écrire) : l'inactif doit vraiment
        # lire la base précédente, sinon le public irait sur une base supprimée.
        inactif = await c.d.app_complete(c.app_id(c.inactif))
        if not nomme_la_base(inactif.get("env"), c.cfg["variable_env"], c.base_precedente):
            raise _Echec("retour_invalide")
        c.marquer("sante")
        await _verifier_sante(c)
        quitte, base_quittee = c.actif, c.base_active
        await _rebaser(c, c.base_precedente)
        await _basculer(c, c.base_precedente, base_quittee, precedente_protegee=True)
        _terminer(c, "reussie",
                  f"Les données écrites depuis la bascule sont dans l'emplacement {quitte} / "
                  f"base {base_quittee}. L'instance {c.inactif} est de nouveau active, "
                  f"base {c.base_precedente}.")

    await _executer(c, deroule)
