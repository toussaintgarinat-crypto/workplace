"""
IPCRA — Input, Projet, Casquette, Ressource, Archive.
Système PKM d'Eliott Meunier pour organiser la connaissance personnelle.

Chaque élément appartient à une des 5 catégories :
  Input      → capture brute non encore traitée (inbox)
  Projet     → projet actif avec un objectif et une deadline
  Casquette  → rôle / responsabilité (chapeau porté dans la vie)
  Ressource  → référence réutilisable, template, connaissance
  Archive    → terminé ou inactif

Intégration MemPalace : chaque item est syncsé dans le palace de l'utilisateur.
Intégration Forge : assistance IA via l'agent assigné.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import httpx
import json
import time

from models.ipcra import IPCRAItem, IPCRATrace, CATEGORIES
from routers.auth import get_current_user
from services.ipcra_service import IPCRAService, get_ipcra_service
import mempalace_client as mp

router = APIRouter()


def _item_dict(item: IPCRAItem) -> dict:
    return {
        "id": item.id,
        "owner_id": item.owner_id,
        "world_id": item.world_id,
        "categorie": item.categorie,
        "titre": item.titre,
        "contenu": item.contenu,
        "tags": json.loads(item.tags or "[]"),
        "casquette": item.casquette,
        "source_url": item.source_url,
        "agent_id": item.agent_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _sync_item(item_id: str, titre: str, contenu: str, categorie: str, user_id: str):
    """Persiste un item dans MemPalace (appelé en BackgroundTask)."""
    if not contenu.strip() and not titre.strip():
        return
    text = f"## {titre}\n\n{contenu}" if contenu.strip() else f"## {titre}"
    mp.sync(text, item_id, categorie, titre, user_id)


# ── CRUD ─────────────────────────────────────────────────────────

class CreateItem(BaseModel):
    titre:      str
    contenu:    str = ""
    categorie:  str = "input"
    tags:       List[str] = []
    casquette:  Optional[str] = None
    source_url: Optional[str] = None
    world_id:   Optional[str] = None
    agent_id:   Optional[str] = None


class UpdateItem(BaseModel):
    titre:      Optional[str] = None
    contenu:    Optional[str] = None
    tags:       Optional[List[str]] = None
    casquette:  Optional[str] = None
    source_url: Optional[str] = None
    agent_id:   Optional[str] = None


@router.get("/")
def list_items(
    categorie: Optional[str] = None,
    world_id: Optional[str] = None,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    if categorie and categorie not in CATEGORIES:
        raise HTTPException(400, f"Catégorie invalide. Valeurs: {CATEGORIES}")
    items = svc.list_items(owner_id=user["id"], categorie=categorie, world_id=world_id)
    return [_item_dict(i) for i in items]


@router.post("/", status_code=201)
def create_item(
    body: CreateItem,
    background_tasks: BackgroundTasks,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    if body.categorie not in CATEGORIES:
        raise HTTPException(400, f"Catégorie invalide. Valeurs: {CATEGORIES}")
    item = svc.create_item(
        owner_id=user["id"],
        world_id=body.world_id,
        categorie=body.categorie,
        titre=body.titre,
        contenu=body.contenu,
        tags=body.tags,
        casquette=body.casquette,
        source_url=body.source_url,
        agent_id=body.agent_id,
    )
    background_tasks.add_task(
        _sync_item, item.id, item.titre, item.contenu, item.categorie, user["id"]
    )
    return _item_dict(item)


@router.get("/{item_id}")
def get_item(
    item_id: str,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    item = svc.get_item(item_id, user["id"])
    if not item:
        raise HTTPException(404)
    return _item_dict(item)


@router.put("/{item_id}")
def update_item(
    item_id: str,
    body: UpdateItem,
    background_tasks: BackgroundTasks,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    item = svc.get_item(item_id, user["id"])
    if not item:
        raise HTTPException(404)
    item = svc.update_item_fields(
        item,
        titre=body.titre, contenu=body.contenu, tags=body.tags,
        casquette=body.casquette, source_url=body.source_url,
        agent_id=body.agent_id,
    )
    background_tasks.add_task(
        _sync_item, item.id, item.titre, item.contenu, item.categorie, user["id"]
    )
    return _item_dict(item)


@router.patch("/{item_id}/categorie")
def move_categorie(
    item_id: str,
    categorie: str,
    background_tasks: BackgroundTasks,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    """Déplace un item vers une autre catégorie (ex: Input → Projet, Projet → Archive)."""
    if categorie not in CATEGORIES:
        raise HTTPException(400, f"Catégorie invalide. Valeurs: {CATEGORIES}")
    item = svc.get_item(item_id, user["id"])
    if not item:
        raise HTTPException(404)
    item = svc.change_categorie(item, categorie)
    background_tasks.add_task(
        _sync_item, item.id, item.titre, item.contenu, item.categorie, user["id"]
    )
    return _item_dict(item)


@router.delete("/{item_id}", status_code=204)
def delete_item(
    item_id: str,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    item = svc.get_item(item_id, user["id"])
    if not item:
        raise HTTPException(404)
    svc.delete_item(item)


# ── Assistance IA via Forge ───────────────────────────────────────

class AssistBody(BaseModel):
    prompt: str


@router.post("/{item_id}/assist")
async def assist_item(
    item_id: str,
    body: AssistBody,
    background_tasks: BackgroundTasks,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    """Demande à l'agent Forge assigné d'assister sur un élément IPCRA."""
    item = svc.get_item(item_id, user["id"])
    if not item:
        raise HTTPException(404)

    agent = None
    if item.agent_id:
        agent = svc.get_active_agent(item.agent_id)

    # Prefetch mémoires pertinentes
    mem_block = ""
    if agent and agent.use_memory:
        hits = mp.prefetch(f"{item.titre} {body.prompt}", n=4, user_id=user["id"])
        mem_block = mp.format_context_block(hits)

    category_guidance = {
        "input":      "Tu aides à traiter et qualifier cette capture brute. Propose si elle doit devenir un Projet, une Ressource, ou une Casquette.",
        "projet":     "Tu aides à structurer et faire avancer ce projet. Propose des prochaines actions concrètes.",
        "casquette":  "Tu aides à définir et clarifier ce rôle/responsabilité. Quelles actions et ressources lui sont associées ?",
        "ressource":  "Tu enrichis cette ressource avec des informations complémentaires, des exemples ou des liens utiles.",
        "archive":    "Tu synthétises les leçons apprises de cet élément archivé. Qu'est-ce qui peut être réutilisé ?",
    }

    system = f"""Tu es un assistant expert en organisation personnelle et PKM (Personal Knowledge Management).
Système utilisé : IPCRA (Input, Projet, Casquette, Ressource, Archive) par Eliott Meunier.

Catégorie de l'élément : {item.categorie.upper()}
{category_guidance.get(item.categorie, '')}

Élément actuel :
## {item.titre}
{item.contenu or '(pas encore de contenu)'}

Tags : {', '.join(json.loads(item.tags or '[]')) or 'aucun'}
{f'Casquette : {item.casquette}' if item.casquette else ''}
{mem_block}

Réponds toujours dans la langue de l'utilisateur."""

    t0 = time.monotonic()

    if agent:
        forge_url = agent.forge_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{forge_url}/api/agents/react",
                    json={
                        "message": body.prompt,
                        "sessionId": f"ipcra-{item_id}",
                        "systemOverride": system,
                        "provider": agent.forge_provider or None,
                        "model": agent.forge_model or None,
                    }
                )
                if r.status_code == 200:
                    data = r.json()
                    duree = int((time.monotonic() - t0) * 1000)
                    background_tasks.add_task(
                        _save_trace,
                        item_id, user["id"], body.prompt,
                        data.get("answer", ""), agent.nom, duree,
                    )
                    return data
        except httpx.ConnectError:
            pass
        return {"answer": f"[Agent Forge non disponible sur {forge_url}]", "steps": []}

    return {
        "answer": (
            f"Aucun agent assigné. Pour utiliser l'IA, assigne un agent Forge à cet élément.\n\n"
            f"**Conseil pour la catégorie {item.categorie}** : {category_guidance.get(item.categorie, '')}"
        ),
        "steps": [],
    }


def _save_trace(item_id, owner_id, prompt, answer, agent_nom, duree_ms):
    from database import SessionLocal
    _db = SessionLocal()
    try:
        trace = IPCRATrace(
            item_id=item_id, owner_id=owner_id,
            prompt=prompt, answer=answer,
            agent_nom=agent_nom, duree_ms=duree_ms,
        )
        _db.add(trace)
        _db.commit()
    finally:
        _db.close()


@router.get("/{item_id}/traces")
def get_traces(
    item_id: str,
    svc: IPCRAService = Depends(get_ipcra_service),
    user=Depends(get_current_user),
):
    item = svc.get_item(item_id, user["id"])
    if not item:
        raise HTTPException(404)
    traces = svc.list_traces(item_id)
    return [
        {
            "id": t.id,
            "prompt": t.prompt,
            "answer": t.answer,
            "agent_nom": t.agent_nom,
            "duree_ms": t.duree_ms,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in traces
    ]


# ── Recherche sémantique via MemPalace ────────────────────────────

@router.get("/search/semantic")
async def semantic_search(
    q: str,
    categorie: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Recherche sémantique dans les items IPCRA via MemPalace."""
    hits = mp.prefetch(q, n=10, wing=categorie, user_id=user["id"])
    return {"query": q, "results": hits}
