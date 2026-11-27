"""Brique « livraison » — exploitation des apps déployées sur Dokploy (S246)."""
import asyncio
import logging
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Livraison — exploitation Dokploy", version="0.3.0")
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


def _lire_cles_api() -> set[str]:
    """`LIVRAISON_API_KEYS` seule (jamais `API_KEYS`). Absente ou vide = mode ouvert."""
    return {k.strip() for k in os.getenv("LIVRAISON_API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    cles = _lire_cles_api()
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not cles:
        return presentee or "public"
    if presentee in cles:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


def cle_api_fermee(cle: str = Depends(cle_api)) -> str:
    """Comme `cle_api` mais FAIL CLOSED (motif `briques/connexion`) : sans
    `LIVRAISON_API_KEYS` configurée, les actions sont refusées (403) AVANT tout appel à
    Dokploy — sinon n'importe qui sur le LAN (ou une page web en CSRF « simple request »)
    pourrait redémarrer/déployer/revenir en arrière. Le Cœur présente la clé via
    `LIVRAISON_KEY` (= l'une des valeurs de `LIVRAISON_API_KEYS`)."""
    if not _lire_cles_api():
        raise HTTPException(403, "Route désactivée : configure LIVRAISON_API_KEYS.")
    return cle


@app.on_event("startup")
def _marquer_operations_interrompues():
    """Une opération restée `en_cours` sur disque n'a plus de tâche vivante : on la clôt."""
    import logging
    import operations
    try:
        operations.marquer_interrompues()
    except OSError:
        # Un état illisible ne doit pas empêcher la brique de servir ses autres capacités ;
        # les opérations longues, elles, refuseront de démarrer tant que le disque est en défaut.
        logging.getLogger(__name__).warning("état des opérations illisible au démarrage",
                                            exc_info=True)


@app.get("/sante")
def sante():
    return {"ok": True, "brique": "livraison",
            "dokploy_configure": bool(os.getenv("DOKPLOY_URL") and os.getenv("DOKPLOY_API_KEY"))}


# ── Capacités de lecture ──
from dokploy import Dokploy, DokployErreur  # noqa: E402
from masque import masquer  # noqa: E402
import repere_rollback  # noqa: E402
import preuve  # noqa: E402
import inventaire  # noqa: E402
import sauvegarde  # noqa: E402
import operations  # noqa: E402
import reset  # noqa: E402
from client_executeur import Executeur, ExecuteurErreur  # noqa: E402
import chiffrement  # noqa: E402
import contrats  # noqa: E402
import donnees_utilisateur as DU  # noqa: E402

TAIL_BRIQUE_MAX = 500
LOGS_MAX = 20000


def fournisseur() -> Dokploy:
    url, cle = os.getenv("DOKPLOY_URL"), os.getenv("DOKPLOY_API_KEY")
    if not url or not cle:
        raise HTTPException(503, "Dokploy non configuré (DOKPLOY_URL / DOKPLOY_API_KEY).")
    return Dokploy(url, cle)


async def _resoudre(d: Dokploy, app_: str) -> dict:
    return _choisir(await d.apps(), app_)


async def _resoudre_actif(d: Dokploy, app_: str) -> dict:
    """Comme `_resoudre`, mais pour les outils qui AGISSENT sur l'instance qui sert le public
    (état, logs, redémarrer, déployer, rollback) : après un reset bleu/vert (actif = B), c'est
    le jumeau. Rend l'app à viser avec `emplacement` (None hors reset). Preuve, inventaire et
    reset restent indexés sur l'app d'origine (`_resoudre`). Le jumeau désigné par son propre
    nom se résout sur lui-même (aucun état d'opérations sous ce nom)."""
    apps = await d.apps()
    a = _choisir(apps, app_)
    try:
        etat = operations.lire(a["nom"])
    except OSError:
        raise HTTPException(503, "état des opérations illisible : instance active inconnue") from None
    emp = (etat or {}).get("emplacements") or {}
    if not (isinstance(emp.get("A"), dict) and emp["A"].get("app_id") == a["id"]):
        return {**a, "emplacement": None}
    b = emp.get("B")
    if etat.get("actif") == "B" and isinstance(b, dict) and b.get("app_id"):
        jumeau = next((x for x in apps if x["id"] == b["app_id"]), None)
        return {**(jumeau or {"id": b["app_id"], "nom": a["nom"] + reset.SUFFIXE_JUMEAU}),
                "emplacement": "B"}
    return {**a, "emplacement": "A"}


def _emplacement(a: dict) -> dict:
    """Réponses d'action : l'emplacement visé n'apparaît que pour une app en bleu/vert."""
    return {"emplacement": a["emplacement"]} if a.get("emplacement") else {}


def _choisir(apps: list, app_: str) -> dict:
    exact = [a for a in apps if a["id"] == app_]
    if not exact:
        exact = [a for a in apps if (a["nom"] or "").lower() == app_.strip().lower()]
    if len(exact) == 1:
        return exact[0]
    candidats = exact or apps
    noms = ", ".join(sorted({f"{a['nom']} ({a.get('projet')}/{a.get('environnement')})"
                             for a in candidats if a["nom"]})) or "aucune"
    raison = "ambiguë" if exact else "introuvable"
    raise HTTPException(404, f"Application {raison} : dites laquelle parmi {noms}.")


def _erreur(e: DokployErreur) -> HTTPException:
    # 504 = délai dépassé APRÈS envoi d'une mutation (peut-être exécutée) ; sinon 502.
    return HTTPException(504 if e.statut == 504 else 502, e.message)


# ── Règle du « courant » (I3) ──
# Courant (= en service) : le déploiement le plus RÉCENT de statut `done` — pas forcément
# `deps[0]` (un déploiement plus récent peut être en `error`/`running`).
# ⚠ À vérifier pendant la preuve LIVE (T12) : le comportement réel de Dokploy après un
# `rollback.rollback` (apparition ou non d'une nouvelle entrée `deployments[]`). S'il n'en crée
# pas, le « courant » calculé ici restera l'ancien déploiement après un rollback.
def _courant(deps: list[dict], repere: Optional[dict] = None) -> Optional[int]:
    """Index (deps du plus récent au plus ancien) du déploiement en service, ou None.

    `repere` (voir `repere_rollback`) : si un rollback a été fait et qu'aucun déploiement plus
    récent n'est apparu depuis, le courant est la version visée par ce rollback."""
    if repere and deps and deps[0].get("id") == repere.get("dernier_id"):
        i = next((i for i, x in enumerate(deps) if x.get("id") == repere.get("cible_id")), None)
        if i is not None:
            return i
    return next((i for i, x in enumerate(deps) if x.get("statut") == "done"), None)


def _rollback_possible(x: dict) -> bool:
    return x.get("statut") == "done" and bool(x.get("rollback_id"))


def _cible_par_defaut(info: dict, repere: Optional[dict] = None) -> Optional[dict]:
    """Le plus récent déploiement `done` ANTÉRIEUR au courant portant un `rollback_id`."""
    deps = info["deploiements"]
    i = _courant(deps, repere)
    if not info["rollback_actif"] or i is None:
        return None
    return next((x for x in deps[i + 1:] if _rollback_possible(x)), None)


def _resume(dep: Optional[dict]) -> Optional[dict]:
    return {k: dep[k] for k in ("titre", "statut", "debut", "fin")} if dep else None


@app.get("/apps")
async def lister_apps(_: str = Depends(cle_api)):
    try:
        return {"apps": await fournisseur().apps()}
    except DokployErreur as e:
        raise _erreur(e)


@app.get("/apps/{app_}/etat")
async def etat_app(app_: str, _: str = Depends(cle_api)):
    d = fournisseur()
    try:
        a = await _resoudre_actif(d, app_)
        info = await d.app(a["id"])
    except DokployErreur as e:
        raise _erreur(e)
    deps = info["deploiements"]
    repere = repere_rollback.lire(a["id"])
    i = _courant(deps, repere)
    return {"nom": info["nom"], "statut": info["statut"], "emplacement": a["emplacement"],
            "rollback_disponible": _cible_par_defaut(info, repere) is not None,
            "dernier_deploiement": _resume(deps[0] if deps else None),
            "en_service": _resume(deps[i] if i is not None else None),
            "via_rollback": bool(i is not None and i != _courant(deps))}


@app.get("/apps/{app_}/logs")
async def logs_app(app_: str, tail: int = 100, _: str = Depends(cle_api)):
    tail = max(1, min(tail, TAIL_BRIQUE_MAX))
    d = fournisseur()
    try:
        a = await _resoudre_actif(d, app_)
        info = await d.app(a["id"])
        if not info["deploiements"]:
            raise HTTPException(404, f"Aucun déploiement pour « {info['nom']} » : pas de logs.")
        logs = await d.logs_deploiement(info["deploiements"][0]["id"], tail)
    except DokployErreur as e:
        raise _erreur(e)
    return {"nom": info["nom"], "deploiement": info["deploiements"][0]["titre"],
            "logs": _masquer_puis_couper(logs)}


def _masquer_puis_couper(logs: str) -> str:
    """Masque le texte COMPLET, puis garde les LOGS_MAX derniers caractères en retirant la
    première ligne partielle : un jeton à cheval sur la coupure ne laisse aucun fragment."""
    texte = masquer(logs)
    if len(texte) <= LOGS_MAX:
        return texte
    texte = texte[-LOGS_MAX:]
    nl = texte.find("\n")
    return texte[nl + 1:] if nl != -1 else texte


# ── Actions réversibles (gardées par approbation côté Cœur, S245) ──
from pydantic import BaseModel, Field  # noqa: E402

TITRE_DEFAUT = "Déploiement demandé via l'assistant"


class CorpsDeployer(BaseModel):
    titre: Optional[str] = None


class CorpsRollback(BaseModel):
    version: Optional[str] = None


@app.post("/apps/{app_}/redemarrer")
async def redemarrer_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:   # 3 appels : project.all, application.one (appName), application.reload
        a = await _resoudre_actif(d, app_)
        info = await d.app(a["id"])
        await d.redemarrer(a["id"], info["app_name"])
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"], **_emplacement(a)}


@app.post("/apps/{app_}/deployer")
async def deployer_app(app_: str, corps: Optional[CorpsDeployer] = None,
                       _: str = Depends(cle_api_fermee)):
    titre = ((corps.titre if corps else None) or "").strip() or TITRE_DEFAUT
    d = fournisseur()
    try:
        a = await _resoudre_actif(d, app_)
        await d.deployer(a["id"], titre)
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"], "titre": titre, **_emplacement(a)}


_ROLLBACK_IMPOSSIBLE = ("retour arrière impossible : le rollback n'est pas activé sur cette app "
                        "ou il n'y a pas de version antérieure")


@app.post("/apps/{app_}/rollback")
async def rollback_app(app_: str, corps: Optional[CorpsRollback] = None,
                       _: str = Depends(cle_api_fermee)):
    version = ((corps.version if corps else None) or "").strip()
    d = fournisseur()
    try:
        a = await _resoudre_actif(d, app_)
        info = await d.app(a["id"])
        deps = info["deploiements"]   # du plus récent au plus ancien
        if version:
            cibles = ([x for x in deps if x["id"] == version]
                      or [x for x in deps if x["titre"] == version])
            if len(cibles) > 1:
                raise HTTPException(409, "version ambiguë : précise l'id du déploiement")
            cible = cibles[0] if cibles else None
            if not (info["rollback_actif"] and cible and _rollback_possible(cible)):
                cible = None
        else:
            cible = _cible_par_defaut(info, repere_rollback.lire(a["id"]))
        if not cible:
            raise HTTPException(409, _ROLLBACK_IMPOSSIBLE)
        await d.rollback(cible["rollback_id"])
        if deps:
            repere_rollback.noter(a["id"], deps[0]["id"], cible["id"])
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"], "version_visee": cible["titre"],
            "rollback_id": cible["rollback_id"], **_emplacement(a)}


@app.get("/apps/{app_}/preuve")
async def preuve_app(app_: str, _: str = Depends(cle_api)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    r = preuve.lire(a["id"]) or {}
    return {"app": a["nom"], "app_id": a["id"], "valide": preuve.valide(a["id"]) is not None,
            "preuve_id": r.get("preuve_id"), "verdict": r.get("verdict"),
            "expire_a": r.get("expire_a"), "comptages": r.get("comptages")}


def exiger_preuve(app_id: str) -> dict:
    """Défense en profondeur : même si le Cœur était contourné, une action `donnees` sans
    preuve de sauvegarde fraîche est refusée par la brique elle-même."""
    r = preuve.valide(app_id)
    if not r:
        raise HTTPException(409, "aucune preuve de sauvegarde valide pour cette application : "
                                 "lance d'abord la vérification de sauvegarde")
    return r


def executeur() -> Executeur:
    url, cle = os.getenv("EXECUTEUR_URL"), os.getenv("EXECUTEUR_KEY")
    if not url or not cle:
        raise HTTPException(503, "Exécuteur de restauration non configuré "
                                 "(EXECUTEUR_URL / EXECUTEUR_KEY).")
    return Executeur(url, cle)


def _entree_inventaire(nom_app: str) -> dict:
    """Après un reset bleu/vert, la sauvegarde et sa vérification suivent la base ACTIVE."""
    e = inventaire.lire(nom_app)
    if not e:
        raise HTTPException(404, "aucun inventaire de sauvegarde valide pour cette application")
    try:
        etat = operations.lire(nom_app)
    except OSError:
        raise HTTPException(503, "état des opérations illisible : base active inconnue") from None
    return reset.base_effective(e, etat)


@app.post("/apps/{app_}/sauvegarder")
async def sauvegarder_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
        r = await sauvegarde.sauvegarder(d, _entree_inventaire(a["nom"]))
    except DokployErreur as e:
        raise _erreur(e)
    except sauvegarde.SauvegardeDesynchronisee as e:
        raise HTTPException(409, str(e)) from None
    return {"ok": True, "app": a["nom"], **r}


@app.post("/apps/{app_}/sauvegardes/verifier")
async def verifier_sauvegarde(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    entree = _entree_inventaire(a["nom"])   # avant executeur() : un 404 prime sur un 503
    r = await sauvegarde.verifier(d, executeur(), entree, a["id"])
    return {"app": a["nom"], "app_id": a["id"], **r}


# ── Reset bleu/vert (S247 2b) ──
_taches_en_fond: set = set()   # références fortes : une tâche sans référence peut être ramassée


def _entree_brute(nom_app: str) -> dict:
    """Entrée d'inventaire TELLE QUE LUE (base racine) : `reset` recalcule lui-même la base
    active depuis l'état des opérations ; `_entree_inventaire` casserait `base_racine`."""
    e = inventaire.lire(nom_app)
    if not e:
        raise HTTPException(404, "aucun inventaire de sauvegarde valide pour cette application")
    return e


def _exiger_reset_configurable(entree: dict) -> None:
    """Refus AVANT le 202 (sinon l'échec n'arrive qu'en fond, après la réservation)."""
    if not entree.get("reset"):
        raise HTTPException(409, "reset non configuré pour cette application")
    base = ((entree.get("bases") or [{}])[0] or {}).get("base")
    if (not isinstance(base, str) or not reset.RE_RACINE.fullmatch(base)
            or reset.RE_GENEREE.fullmatch(base)):
        raise HTTPException(409, "configuration invalide : nom de base trop long ou hors motif "
                                 "pour un reset (31 caractères au plus, [a-z0-9_])")
    if not os.getenv("LIVRAISON_TRAEFIK_URL"):
        raise HTTPException(503, "LIVRAISON_TRAEFIK_URL non configuré : contrôle de santé de "
                                 "l'instance neuve impossible")


def _lancer(app_nom: str, type_: str, coro_fabrique) -> dict:
    """Réserve l'opération (409 si déjà en cours) puis lance la tâche de fond ; 202."""
    try:
        oid = operations.demarrer(app_nom, type_)
    except operations.OperationEnCours:
        raise HTTPException(409, "une opération est déjà en cours pour cette application") from None
    except OSError:
        raise HTTPException(503, "état des opérations illisible") from None
    tache = asyncio.create_task(coro_fabrique(oid))
    _taches_en_fond.add(tache)
    tache.add_done_callback(_taches_en_fond.discard)
    return {"ok": True, "app": app_nom, "operation": oid, "etat": "en_cours"}


@app.post("/apps/{app_}/reset", status_code=202)
async def reset_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    entree = _entree_brute(a["nom"])
    _exiger_reset_configurable(entree)
    ex = executeur()
    exiger_preuve(a["id"])
    return _lancer(a["nom"], "reset", lambda oid: reset.reset(d, ex, entree, a["nom"], a["id"], oid))


@app.post("/apps/{app_}/retour-arriere", status_code=202)
async def retour_arriere_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    entree = _entree_brute(a["nom"])
    _exiger_reset_configurable(entree)
    try:
        etat = operations.lire(a["nom"])
    except OSError:
        raise HTTPException(503, "état des opérations illisible") from None
    if not reset.peut_retour_arriere(etat):
        raise HTTPException(409, "aucun retour arrière possible pour cette application")
    return _lancer(a["nom"], "retour_arriere",
                   lambda oid: reset.retour_arriere(d, entree, a["nom"], oid))


@app.get("/apps/{app_}/operation")
async def operation_app(app_: str, _: str = Depends(cle_api)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    try:
        etat = operations.lire(a["nom"])
    except OSError:
        raise HTTPException(503, "état des opérations illisible") from None
    op = (etat or {}).get("op") or {}
    return {"app": a["nom"], "etat": op.get("etat") or "aucune", "etape": op.get("etape"),
            "operation": op.get("id"), "message": op.get("message"),
            "actif": (etat or {}).get("actif"), "base_active": (etat or {}).get("base_active"),
            "retour_possible": reset.peut_retour_arriere(etat)}


# ── Données utilisateur (S248 3a) ──
class CorpsUtilisateur(BaseModel):
    utilisateur: str = Field(pattern=r"^[A-Za-z0-9_.@-]{1,128}$")   # moteur regex Rust (pydantic v2) : pas de \Z ; `$` = fin de texte stricte


def _traduire(e: Exception) -> HTTPException:
    if isinstance(e, contrats.ContratErreur):
        return HTTPException(e.statut if e.statut in (404, 409, 422, 503) else 502, e.message)
    if isinstance(e, chiffrement.CleAbsente):
        return HTTPException(503, "chiffrement des paquets non configuré (LIVRAISON_CHIFFREMENT_CLE)")
    if isinstance(e, ExecuteurErreur):
        return HTTPException(502, e.message)
    if isinstance(e, OSError):
        return HTTPException(503, "registre des paquets illisible")
    return HTTPException(500, "erreur interne")


async def _donnees(app_: str, fabrique, sur_delai):
    """Garde commune : 503 sans clé, contrat/exécuteur résolus, budget GLOBAL (le Cœur coupe plus
    tard : jamais de coupure mid-flight). `sur_delai()` rend le résultat (ou lève) à l'expiration."""
    try:
        chiffrement._cle()                    # 503 avant tout appel à l'app (fail closed)
        app = contrats.ouvrir(app_)
        ex = executeur()
        try:
            return await asyncio.wait_for(fabrique(app, ex), DU.DELAI_GLOBAL_DONNEES_S)
        except asyncio.TimeoutError:          # avant OSError (TimeoutError en est une sous-classe)
            return sur_delai()
    except DU.RefusDonnees as e:
        raise HTTPException(e.statut, e.message) from None
    except (contrats.ContratErreur, chiffrement.CleAbsente, ExecuteurErreur, OSError) as e:
        raise _traduire(e) from None


def _delai(message: str):
    def f():
        raise HTTPException(504, message)
    return f


@app.post("/contrats/{app_}/exporter")
async def exporter_donnees(app_: str, corps: CorpsUtilisateur, _: str = Depends(cle_api_fermee)):
    r = await _donnees(app_, lambda a, ex: DU.exporter_et_stocker(a, ex, corps.utilisateur),
                       _delai("délai global dépassé : l'export a peut-être été stocké, relance"))
    r.pop("h")
    return {"ok": True, "app": app_.strip().lower(), **r}


def _verdict_delai() -> dict:
    """Délai global de vérification : verdict invalide S247-style, jamais marqué vérifié (le Cœur
    ignore un verdict sans `preuve_id`)."""
    return {"ok": True, "verdict": "invalide", "paquet_id": None, "preuve_id": None,
            "empreinte": None, "comptages": None, "expire_a": None,
            "raisons": ["délai global de vérification dépassé"]}


@app.post("/contrats/{app_}/verifier")
async def verifier_donnees(app_: str, corps: CorpsUtilisateur, _: str = Depends(cle_api_fermee)):
    r = await _donnees(app_, lambda a, ex: DU.verifier_paquet(a, ex, corps.utilisateur), _verdict_delai)
    return {"app": app_.strip().lower(), **r}


class CorpsRestitution(CorpsUtilisateur):
    paquet_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}$")


@app.post("/contrats/{app_}/reinitialiser")
async def reinitialiser_donnees(app_: str, corps: CorpsUtilisateur, _: str = Depends(cle_api_fermee)):
    suivi: dict = {}              # le paquet choisi par l'orchestration, lisible si le budget tombe
    r = await _donnees(app_, lambda a, ex: DU.reinitialiser_donnees(a, ex, corps.utilisateur, suivi=suivi),
                       lambda: _delai(DU.message_delai_reset(suivi.get("paquet_id")))())
    return {"app": app_.strip().lower(), **r}


@app.post("/contrats/{app_}/restituer")
async def restituer_donnees(app_: str, corps: CorpsRestitution, _: str = Depends(cle_api_fermee)):
    r = await _donnees(app_, lambda a, ex: DU.restituer_donnees(a, ex, corps.utilisateur,
                                                                corps.paquet_id),
                       _delai("délai global dépassé : la restitution a peut-être été appliquée, "
                              "vérifie l'état avant de réessayer"))
    return {"app": app_.strip().lower(), **r}


@app.post("/contrats/purger")
async def purger_contrats(_: str = Depends(cle_api_fermee)):
    try:
        return {"ok": True, **await DU.purger_expires(executeur())}
    except ExecuteurErreur as e:
        raise _traduire(e) from None


async def _purger_une_fois():
    try:
        await DU.purger_expires(executeur())
    except Exception as exc:        # exécuteur non configuré/injoignable : on réessaiera
        logging.getLogger(__name__).warning("purge des paquets en échec : %s", type(exc).__name__)


async def _boucle_purge():
    while True:
        await _purger_une_fois()
        await asyncio.sleep(3600)


@app.on_event("startup")
async def _demarrer_purge():
    t = asyncio.create_task(_boucle_purge())
    _taches_en_fond.add(t)
    t.add_done_callback(_taches_en_fond.discard)
