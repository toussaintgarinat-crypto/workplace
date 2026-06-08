"""
Router Intercommunalité — Documents partagés entre worlds en réseau.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.auth import get_current_user
from models.document import Document
from models.world import World
from services.reseau_service import ReseauService, get_reseau_service

router = APIRouter()


def _categorise(nom: str) -> str:
    n = nom.lower()
    if any(k in n for k in ("deliber", "délibér", "deliberation")):
        return "deliberation"
    if any(k in n for k in ("arrete", "arrêté", "arrête")):
        return "arrete"
    return "autre"


def _doc_dict(doc: Document, world: World) -> dict:
    return {
        "id":          doc.id,
        "nom":         doc.nom,
        "nom_original": doc.nom_original,
        "type_mime":   doc.type_mime,
        "taille":      doc.taille,
        "created_at":  doc.created_at.isoformat(),
        "partage_reseau": doc.partage_reseau,
        "commune": {
            "id":    world.id,
            "nom":   world.nom,
            "emoji": world.emoji,
        },
    }


@router.get("/documents")
def documents_reseau(
    world_id: str,
    svc: ReseauService = Depends(get_reseau_service),
    user=Depends(get_current_user),
):
    if not svc.is_member(world_id, user["id"]):
        raise HTTPException(403)

    linked_ids = svc.linked_world_ids(world_id)
    if not linked_ids:
        return {"communes": [], "deliberations": [], "arretes": [], "autres": []}

    worlds = svc.get_worlds_map(linked_ids)
    docs = svc.list_shared_docs_for_worlds(linked_ids)

    deliberations, arretes, autres = [], [], []
    for doc in docs:
        world = worlds.get(doc.world_id)
        if not world:
            continue
        d = _doc_dict(doc, world)
        cat = _categorise(doc.nom_original or doc.nom)
        if cat == "deliberation":
            deliberations.append(d)
        elif cat == "arrete":
            arretes.append(d)
        else:
            autres.append(d)

    communes = [
        {"id": w.id, "nom": w.nom, "emoji": w.emoji}
        for w in worlds.values()
    ]

    return {
        "communes":      communes,
        "deliberations": deliberations,
        "arretes":       arretes,
        "autres":        autres,
    }


@router.get("/documents/mes-docs")
def mes_docs_partageables(
    world_id: str,
    svc: ReseauService = Depends(get_reseau_service),
    user=Depends(get_current_user),
):
    """Documents de l'utilisateur dans ce world — pour gérer le partage réseau."""
    if not svc.is_member(world_id, user["id"]):
        raise HTTPException(403)

    docs = svc.list_user_docs_in_world(user["id"], world_id)
    return [
        {
            "id":           d.id,
            "nom":          d.nom,
            "nom_original": d.nom_original,
            "type_mime":    d.type_mime,
            "taille":       d.taille,
            "created_at":   d.created_at.isoformat(),
            "partage_reseau": d.partage_reseau,
        }
        for d in docs
    ]


class PartagerBody(BaseModel):
    doc_id:  str
    partage: bool


@router.post("/documents/partager")
def partager_document(
    body: PartagerBody,
    svc: ReseauService = Depends(get_reseau_service),
    user=Depends(get_current_user),
):
    """Active ou désactive le partage réseau d'un document appartenant à l'utilisateur."""
    doc = svc.get_owned_document(body.doc_id, user["id"])
    if not doc:
        raise HTTPException(404, "Document introuvable ou accès refusé")
    svc.set_doc_partage_reseau(doc, body.partage)
    return {"ok": True, "doc_id": doc.id, "partage_reseau": doc.partage_reseau}
