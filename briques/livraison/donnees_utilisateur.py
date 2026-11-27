"""Orchestration des paquets de données utilisateur (S248 3a) : export → chiffrement → dépôt
SeaweedFS (via l'exécuteur) → registre ; vérification par RELECTURE du stockage. Jamais le contenu
en retour, jamais l'identité en clair."""
import asyncio
import time
from typing import Optional

import chiffrement
import paquets
from client_executeur import ExecuteurErreur


async def exporter_et_stocker(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    h = paquets.empreinte_utilisateur(utilisateur)
    paquet, meta = await app.exporter(utilisateur)
    pid = paquets.nouveau_id()
    objet = paquets.cle_objet(app.nom, h, pid)
    await ex.deposer(objet, chiffrement.chiffrer(paquet, objet))
    try:
        rec = paquets.enregistrer(pid, app.nom, h, objet, meta["empreinte"], meta["comptages"],
                                  app.version_schema, maintenant)
    except OSError:
        try:
            await ex.supprimer(objet)     # pas d'objet orphelin hors registre
        except ExecuteurErreur:
            pass
        raise
    paquets.journaliser("exporter", app.nom, h, pid, True, maintenant)
    return {"paquet_id": pid, "empreinte": rec["empreinte"], "comptages": rec["comptages"],
            "version_schema": rec["version_schema"], "expire_a": rec["expire_a"], "h": h}


async def verifier_paquet(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    """Exporte à neuf, stocke, RELIT depuis le stockage, déchiffre, et fait vérifier CE paquet par
    l'app (import dans un dossier jetable + ré-export + même empreinte). Toute défaillance donne un
    verdict `invalide` avec `ok: True` (fail closed, convention S247)."""
    from contrats import ContratErreur
    r = await exporter_et_stocker(app, ex, utilisateur, maintenant)
    pid, raisons = r["paquet_id"], []
    try:
        rec = paquets.lire(pid)
        if rec is None:
            raise LookupError
        blob = await ex.lire(rec["objet"])
        clair = chiffrement.dechiffrer(blob, rec["objet"])
        retour = await app.verifier(utilisateur, clair)
        if retour.get("ok") is not True or retour.get("empreinte") != rec["empreinte"]:
            raisons.append("l'application ne confirme pas l'empreinte exportée")
    except chiffrement.Illisible:
        raisons.append("paquet relu illisible (altéré ou mauvaise clé)")
    except ContratErreur as e:
        raisons.append(f"refus de l'application : {e.raison or 'erreur'}")
    except ExecuteurErreur as e:
        raisons.append(f"stockage : {e.message}")
    except LookupError:
        raisons.append("paquet introuvable dans le registre")
    except Exception:   # fail closed : jamais d'exception brute (ni son message) vers l'appelant
        raisons.append("erreur inattendue pendant la vérification")
    verdict = "valide" if not raisons else "invalide"
    if verdict == "valide":
        paquets.marquer_verifie(pid, maintenant)
    paquets.journaliser("verifier", app.nom, r["h"], pid, verdict == "valide", maintenant)
    now = maintenant if maintenant is not None else time.time()
    return {"ok": True, "verdict": verdict, "paquet_id": pid, "empreinte": r["empreinte"],
            "comptages": r["comptages"], "raisons": raisons,
            "expire_a": min(now + paquets.PREUVE_TTL_S, r["expire_a"])}


async def purger_expires(ex, maintenant: Optional[float] = None) -> dict:
    supprimes = restants = 0
    for rec in paquets.expires(maintenant):
        try:
            await ex.supprimer(rec["objet"])
            paquets.retirer(rec["id"])
            paquets.journaliser("purger", rec["app"], rec["h"], rec["id"], True, maintenant)
        except (ExecuteurErreur, OSError, KeyError, TypeError, ValueError):
            restants += 1          # on réessaiera : une entrée en échec n'arrête pas les autres
            continue
        supprimes += 1
    return {"supprimes": supprimes, "restants": restants}


class RefusDonnees(Exception):
    """Refus d'orchestration : `.message` est une chaîne FIXE (jamais l'utilisateur, une clé ni un
    corps de réponse), `.statut` le code HTTP à restituer."""

    def __init__(self, statut: int, message: str):
        super().__init__(message)
        self.statut, self.message = statut, message


_EN_COURS: set = set()     # (app, h) ayant une opération en cours : un reset ne double jamais
_RACINE_AMBIGU = ("l'application n'a pas répondu : la remise à zéro a peut-être été effectuée, "
                  "vérifie avec livraison_donnees_verifier avant de réessayer")


_AVANT_EFFET = (401, 404, 413, 409, 422)
_RAISONS_NON_ENVOYEES = ("injoignable", "identite")   # la requête n'est jamais partie
_MESSAGES_NON_ENVOYEE = {"injoignable": "application injoignable : rien n'a été modifié",
                         "identite": "identité non transmissible : rien n'a été modifié"}
_SUITE_RESTITUABLE = "reste restituable avec livraison_donnees_restituer (paquet_id)"


def _certain_avant_effet(e) -> bool:
    """Seuls ces refus se lisent « rien n'a été fait » ; tout le reste (pas de statut, 5xx, 200
    illisible) est ambigu : l'application n'a pas de retour arrière, l'effet peut avoir eu lieu."""
    return (e.statut in _AVANT_EFFET or (e.statut == 503 and e.raison == "desactive")
            or (e.statut is None and e.raison in _RAISONS_NON_ENVOYEES))


def _tout_a_zero(comptages, cles=None) -> bool:
    """Tous les comptages valent exactement 0 ; avec `cles` (comptages de référence), ils doivent
    aussi avoir exactement les MÊMES clés (une application qui en perd une n'est pas « à zéro »)."""
    if cles is not None and not (isinstance(cles, dict) and isinstance(comptages, dict)
                                 and set(comptages) == set(cles)):
        return False
    return (isinstance(comptages, dict) and bool(comptages)
            and all(type(v) is int and v == 0 for v in comptages.values()))


def _journal(operation: str, app: str, h: str, pid: str, ok: bool, maintenant) -> None:
    """Journal au mieux APRÈS un effet irréversible : une erreur disque ne change pas l'issue."""
    try:
        paquets.journaliser(operation, app, h, pid, ok, maintenant)
    except OSError:
        pass


async def _relire(ex, rec) -> bytes:
    try:
        return chiffrement.dechiffrer(await ex.lire(rec["objet"]), rec["objet"])
    except chiffrement.Illisible:
        raise RefusDonnees(409, "paquet stocké illisible (altéré ou clé changée) : "
                                "refais une vérification") from None
    except (ExecuteurErreur, chiffrement.CleAbsente, KeyError, OSError):
        raise RefusDonnees(502, "paquet stocké inaccessible : rien n'a été touché, réessaie plus "
                                "tard") from None


def _refus_app(e, avant_effacement: bool) -> RefusDonnees:
    statut = 409 if e.statut in (409, 422) else 502
    suite = " ; les données sont intactes" if avant_effacement else ""
    return RefusDonnees(statut, f"l'application refuse : {e.raison or 'erreur'}{suite}")


def _refus_non_envoye(e) -> RefusDonnees:
    """Refus certain avant effet d'un appel d'effet (reset/import) : requête jamais partie, ou
    refus net de l'application."""
    if e.statut is None and e.raison in _MESSAGES_NON_ENVOYEE:
        return RefusDonnees(502, _MESSAGES_NON_ENVOYEE[e.raison])
    return _refus_app(e, False)


def _consommer(pid: str, maintenant) -> None:
    try:
        paquets.marquer_consomme(pid, maintenant)
    except OSError:
        pass


def _prendre(app, h):
    cible = (app.nom, h)
    if cible in _EN_COURS:
        raise RefusDonnees(409, "une opération est déjà en cours pour cet utilisateur")
    _EN_COURS.add(cible)
    return cible


async def reinitialiser_donnees(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    """Efface les données d'UN utilisateur, sous preuve fraîche (≤ 6 h), empreinte inchangée.
    Avant `app.reinitialiser` : tout échec laisse les données intactes. Après : plus aucune
    exception brute ni refus laissant croire que rien n'a eu lieu."""
    from contrats import ContratErreur
    h = paquets.empreinte_utilisateur(utilisateur)
    cible = _prendre(app, h)
    try:
        rec = paquets.dernier_verifie(app.nom, h, maintenant)           # preuve ≤ 6 h
        if rec is None:
            raise RefusDonnees(409, "aucun paquet vérifié et récent pour cet utilisateur : "
                                    "lance d'abord livraison_donnees_verifier")
        await _relire(ex, rec)                         # le paquet est TOUJOURS restituable
        try:
            _, meta = await app.exporter(utilisateur)
        except ContratErreur as e:
            raise _refus_app(e, True) from None
        avant = meta.get("comptages")
        if meta.get("empreinte") != rec["empreinte"]:
            raise RefusDonnees(409, "les données ont changé depuis la vérification : "
                                    "relance livraison_donnees_verifier")
        try:
            r = await app.reinitialiser(utilisateur, rec["empreinte"])
        except ContratErreur as e:
            if e.raison == "empreinte":
                raise RefusDonnees(409, "les données ont changé depuis la vérification : "
                                        "relance livraison_donnees_verifier") from None
            if not _certain_avant_effet(e):                 # effacement peut-être fait
                _consommer(rec["id"], maintenant)
                _journal("reinitialiser", app.nom, h, rec["id"], False, maintenant)
                raise RefusDonnees(504, f"{_RACINE_AMBIGU} ; le paquet {rec['id']} reste "
                                        "restituable avec livraison_donnees_restituer") from None
            raise _refus_non_envoye(e) from None
        except asyncio.CancelledError:
            _consommer(rec["id"], maintenant)               # l'effacement a pu avoir lieu
            raise
        # --- ICI les données sont effacées : plus rien ne doit se lire comme « rien ne s'est passé » ---
        _consommer(rec["id"], maintenant)                           # d'abord, au mieux
        try:
            _, apres = await app.exporter(utilisateur)
            reste = apres["comptages"]
            zero = _tout_a_zero(reste, avant)
        except Exception:
            _journal("reinitialiser", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(502, "remise à zéro effectuée mais le contrôle final a échoué : "
                                    f"vérifie l'état de l'application ; le paquet {rec['id']} "
                                    f"{_SUITE_RESTITUABLE}") from None
        _journal("reinitialiser", app.nom, h, rec["id"], zero, maintenant)
        if not zero:
            raise RefusDonnees(409, "remise à zéro au résultat incomplet : des données sont réapparues (une "
                                    f"opération de l'application était en cours) ; le paquet {rec['id']} "
                                    f"{_SUITE_RESTITUABLE}")
        supprimes = r.get("supprimes", {}) if isinstance(r, dict) else {}
        return {"ok": True, "etat": "reinitialise", "paquet_id": rec["id"], "supprimes": supprimes}
    finally:
        _EN_COURS.discard(cible)


async def restituer_donnees(app, ex, utilisateur: str, paquet_id: Optional[str] = None,
                            maintenant: Optional[float] = None) -> dict:
    from contrats import ContratErreur
    h = paquets.empreinte_utilisateur(utilisateur)
    cible = _prendre(app, h)
    try:
        now = maintenant if maintenant is not None else time.time()
        if paquet_id:                         # choix délibéré : peut écraser, pas d'état exigé
            rec = paquets.lire(paquet_id)
            if not (isinstance(rec, dict) and rec.get("app") == app.nom and rec.get("h") == h
                    and paquets._date_verif(rec, now) is not None):
                raise RefusDonnees(404, "paquet introuvable, expiré ou non vérifié pour cet "
                                        "utilisateur")
        else:
            candidats = paquets.candidats_a_restituer(app.nom, h, now)
            if not candidats:
                raise RefusDonnees(404, "aucun paquet à restituer : aucune remise à zéro n'a "
                                        "consommé de paquet pour cet utilisateur (précise "
                                        "paquet_id pour un paquet vérifié)")
            if len(candidats) > 1:
                raise RefusDonnees(409, "plusieurs paquets sont candidats ("
                                        + ", ".join(c["id"] for c in candidats)
                                        + ") : précise paquet_id")
            rec = candidats[0]
            try:                                # lecture seule : jamais d'écrasement silencieux
                _, actuel = await app.exporter(utilisateur)
            except ContratErreur as e:
                raise _refus_app(e, True) from None
            if not (_tout_a_zero(actuel.get("comptages"), rec.get("comptages"))
                    or actuel.get("empreinte") == rec["empreinte"]):
                raise RefusDonnees(409, "l'état actuel de l'utilisateur n'est ni vide ni identique "
                                        f"au paquet {rec['id']} : rien n'a été restitué ; précise "
                                        "paquet_id pour écraser volontairement")
        clair = await _relire(ex, rec)
        try:
            await app.importer(utilisateur, clair)
        except ContratErreur as e:
            _journal("restituer", app.nom, h, rec["id"], False, maintenant)
            if not _certain_avant_effet(e):                 # import peut-être partiel
                raise RefusDonnees(504, "l'application n'a pas répondu : la restitution a peut-être "
                                        "été appliquée, vérifie l'état avant de réessayer") from None
            raise _refus_non_envoye(e) from None
        try:
            _, apres = await app.exporter(utilisateur)
        except Exception:
            _journal("restituer", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(502, "restitution appliquée mais le contrôle final a échoué : "
                                    f"vérifie l'état de l'application ; le paquet {rec['id']} "
                                    f"{_SUITE_RESTITUABLE}") from None
        if apres["empreinte"] != rec["empreinte"]:
            _journal("restituer", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(409, "restitution incomplète : l'état restauré ne correspond pas "
                                    "au paquet")
        try:
            paquets.marquer_restitue(rec["id"], maintenant)
        except OSError:
            pass
        _journal("restituer", app.nom, h, rec["id"], True, maintenant)
        return {"ok": True, "etat": "restitue", "paquet_id": rec["id"],
                "comptages": apres["comptages"]}
    finally:
        _EN_COURS.discard(cible)
