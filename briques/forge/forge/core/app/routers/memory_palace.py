"""Router MemPalace — proxy vers la brique Mémoire Workplace (port 5600).

Remplace DEUX choses historiques :
- l'ancien stockage clé/valeur de Forge (table ``memory_entries``, modèle retiré) ;
- l'ancien palace externe que le front interrogeait en direct (``localhost:8100``,
  login séparé ``mp_token``).

Désormais la vue MemPalace de Forge consulte la **brique Mémoire** via son contrat
simple (``/retenir`` / ``/rappeler`` / ``/souvenirs`` / ``/taxonomy`` / ``DELETE``),
en isolant chaque organisation dans un espace dédié (« forge-org-<id> ») — l'isolation
multi-tenant S18 est ainsi préservée jusque dans la mémoire. La brique encapsule
espaces, JWT et le projet Memory (graphe IPCRa / pgvector).

Monté sous ``/api``. Routes protégées (utilisateur + org active).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import UserContext, get_current_user, require_org
from app.config import settings

router = APIRouter()

# Wings de la vue = types de nœuds IPCRa côté brique/Memory.
WINGS = {"input", "projet", "casquette", "ressource", "archive"}


def _espace(org_id: str | None) -> str:
    """Un espace mémoire par org (isolation S18). Repli = espace solution de la brique."""
    if org_id:
        return f"forge-org-{org_id}"
    return settings.MEMOIRE_ESPACE or "Workplace"


def _base() -> str:
    return settings.MEMOIRE_URL.rstrip("/")


async def _brique(method: str, path: str, **kw):
    """Appel best-effort borné à la brique Mémoire. 503 si non configurée, 502 si KO."""
    if not settings.MEMOIRE_URL:
        raise HTTPException(503, "Brique Mémoire non configurée (MEMOIRE_URL absent)")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.request(method, f"{_base()}{path}", **kw)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Brique Mémoire injoignable : {e}")
    if r.status_code >= 400:
        raise HTTPException(502, f"Mémoire ({r.status_code}) : {r.text[:200]}")
    return r.json()


@router.get("/memory/taxonomy")
async def taxonomy(
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    """Comptes par wing (type) pour les onglets de la vue."""
    data = await _brique("GET", "/taxonomy", params={"espace": _espace(org_id)})
    return {"total": data.get("total", 0), "wings": data.get("par_type", {})}


@router.get("/memory")
async def list_memory(
    wing: str | None = None,
    limite: int = 100,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    """Liste les souvenirs (filtrés par wing si fourni)."""
    params: dict = {"espace": _espace(org_id), "limite": limite}
    if wing:
        params["type"] = wing if wing in WINGS else "input"
    data = await _brique("GET", "/souvenirs", params=params)
    return data.get("souvenirs", [])


@router.get("/memory/search")
async def search_memory(
    q: str,
    wing: str | None = None,
    limite: int = 10,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    """Recherche hybride (texte + vecteur) déléguée à la brique."""
    params: dict = {"q": q, "espace": _espace(org_id), "limite": limite}
    if wing:
        params["type"] = wing if wing in WINGS else "input"
    data = await _brique("GET", "/rappeler", params=params)
    return {"results": data.get("souvenirs", [])}


class NouveauSouvenir(BaseModel):
    contenu: str = Field(min_length=1)
    wing: str = "input"          # type de nœud IPCRa
    room: str = "general"        # sous-rangement
    metadata: dict | None = None


@router.post("/memory", status_code=201)
async def create_memory(
    body: NouveauSouvenir,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    type_ = body.wing if body.wing in WINGS else "input"
    # On marque le sujet (user_id) en métadonnée pour une attribution future.
    meta = {**(body.metadata or {}), "user_id": user.sub}
    return await _brique("POST", "/retenir", json={
        "contenu": body.contenu,
        "type": type_,
        "wing": type_,
        "room": body.room or "general",
        "metadata": meta,
        "espace": _espace(org_id),
    })


@router.delete("/memory/{souvenir_id}")
async def delete_memory(
    souvenir_id: str,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    return await _brique("DELETE", f"/souvenir/{souvenir_id}",
                         params={"espace": _espace(org_id)})
