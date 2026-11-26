"""Brique « livraison » — exploitation des apps déployées sur Dokploy (S246)."""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Livraison — exploitation Dokploy", version="0.1.0")
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
from client_executeur import Executeur  # noqa: E402

TAIL_BRIQUE_MAX = 500
LOGS_MAX = 20000


def fournisseur() -> Dokploy:
    url, cle = os.getenv("DOKPLOY_URL"), os.getenv("DOKPLOY_API_KEY")
    if not url or not cle:
        raise HTTPException(503, "Dokploy non configuré (DOKPLOY_URL / DOKPLOY_API_KEY).")
    return Dokploy(url, cle)


async def _resoudre(d: Dokploy, app_: str) -> dict:
    apps = await d.apps()
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
        a = await _resoudre(d, app_)
        info = await d.app(a["id"])
    except DokployErreur as e:
        raise _erreur(e)
    deps = info["deploiements"]
    repere = repere_rollback.lire(a["id"])
    i = _courant(deps, repere)
    return {"nom": info["nom"], "statut": info["statut"],
            "rollback_disponible": _cible_par_defaut(info, repere) is not None,
            "dernier_deploiement": _resume(deps[0] if deps else None),
            "en_service": _resume(deps[i] if i is not None else None),
            "via_rollback": bool(i is not None and i != _courant(deps))}


@app.get("/apps/{app_}/logs")
async def logs_app(app_: str, tail: int = 100, _: str = Depends(cle_api)):
    tail = max(1, min(tail, TAIL_BRIQUE_MAX))
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
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
from pydantic import BaseModel  # noqa: E402

TITRE_DEFAUT = "Déploiement demandé via l'assistant"


class CorpsDeployer(BaseModel):
    titre: Optional[str] = None


class CorpsRollback(BaseModel):
    version: Optional[str] = None


@app.post("/apps/{app_}/redemarrer")
async def redemarrer_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:   # 3 appels : project.all, application.one (appName), application.reload
        a = await _resoudre(d, app_)
        info = await d.app(a["id"])
        await d.redemarrer(a["id"], info["app_name"])
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"]}


@app.post("/apps/{app_}/deployer")
async def deployer_app(app_: str, corps: Optional[CorpsDeployer] = None,
                       _: str = Depends(cle_api_fermee)):
    titre = ((corps.titre if corps else None) or "").strip() or TITRE_DEFAUT
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
        await d.deployer(a["id"], titre)
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"], "titre": titre}


_ROLLBACK_IMPOSSIBLE = ("retour arrière impossible : le rollback n'est pas activé sur cette app "
                        "ou il n'y a pas de version antérieure")


@app.post("/apps/{app_}/rollback")
async def rollback_app(app_: str, corps: Optional[CorpsRollback] = None,
                       _: str = Depends(cle_api_fermee)):
    version = ((corps.version if corps else None) or "").strip()
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
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
            "rollback_id": cible["rollback_id"]}


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
    e = inventaire.lire(nom_app)
    if not e:
        raise HTTPException(404, "aucun inventaire de sauvegarde valide pour cette application")
    return e


@app.post("/apps/{app_}/sauvegarder")
async def sauvegarder_app(app_: str, _: str = Depends(cle_api_fermee)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
        r = await sauvegarde.sauvegarder(d, _entree_inventaire(a["nom"]))
    except DokployErreur as e:
        raise _erreur(e)
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
