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


@app.get("/sante")
def sante():
    return {"ok": True, "brique": "livraison",
            "dokploy_configure": bool(os.getenv("DOKPLOY_URL") and os.getenv("DOKPLOY_API_KEY"))}


# ── Capacités de lecture ──
from dokploy import Dokploy, DokployErreur  # noqa: E402
from masque import masquer  # noqa: E402

TAIL_BRIQUE_MAX = 500


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
    noms = ", ".join(sorted({a["nom"] for a in apps if a["nom"]})) or "aucune"
    raison = "ambiguë" if exact else "introuvable"
    raise HTTPException(404, f"Application {raison} : dites laquelle parmi {noms}.")


def _erreur(e: DokployErreur) -> HTTPException:
    return HTTPException(502, e.message)


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
    dernier = ({k: deps[0][k] for k in ("titre", "statut", "debut", "fin")} if deps else None)
    rollback = bool(info["rollback_actif"] and any(x.get("rollback_id") for x in deps[1:]))
    return {"nom": info["nom"], "statut": info["statut"],
            "rollback_disponible": rollback, "dernier_deploiement": dernier}


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
            "logs": masquer(logs)}


# ── Actions réversibles (gardées par approbation côté Cœur, S245) ──
from pydantic import BaseModel  # noqa: E402

TITRE_DEFAUT = "Déploiement demandé via l'assistant"


class CorpsDeployer(BaseModel):
    titre: Optional[str] = None


class CorpsRollback(BaseModel):
    version: Optional[str] = None


@app.post("/apps/{app_}/redemarrer")
async def redemarrer_app(app_: str, _: str = Depends(cle_api)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
        await d.redemarrer(a["id"])
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"]}


@app.post("/apps/{app_}/deployer")
async def deployer_app(app_: str, corps: Optional[CorpsDeployer] = None,
                       _: str = Depends(cle_api)):
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
                       _: str = Depends(cle_api)):
    version = ((corps.version if corps else None) or "").strip()
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
        deps = (await d.app(a["id"]))["deploiements"]   # du plus récent au plus ancien
        if version:
            cibles = ([x for x in deps if x["id"] == version]
                      or [x for x in deps if x["titre"] == version])
            cible = cibles[0] if cibles else None
        else:
            cible = next((x for x in deps[1:] if x.get("rollback_id")), None)
        if not cible or not cible.get("rollback_id"):
            raise HTTPException(409, _ROLLBACK_IMPOSSIBLE)
        await d.rollback(cible["rollback_id"])
    except DokployErreur as e:
        raise _erreur(e)
    return {"ok": True, "app": a["nom"], "version_visee": cible["titre"],
            "rollback_id": cible["rollback_id"]}
