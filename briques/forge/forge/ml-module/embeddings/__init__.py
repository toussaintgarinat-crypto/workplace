"""
Module embeddings — génère des vecteurs via modèles locaux HuggingFace.
Utilisé quand on ne veut pas dépendre d'une API externe pour les embeddings.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from typing import List

router = APIRouter()

# Modèle local chargé une seule fois au démarrage
_model: SentenceTransformer | None = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    model: str
    dimensions: int


@router.post("/", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    """Génère des embeddings locaux pour une liste de textes."""
    model = get_model()
    vectors = model.encode(req.texts, normalize_embeddings=True).tolist()
    return EmbedResponse(
        embeddings=vectors,
        model="all-MiniLM-L6-v2",
        dimensions=len(vectors[0]) if vectors else 384,
    )


@router.get("/models")
def list_models():
    """Liste les modèles d'embedding disponibles localement."""
    return {
        "models": [
            {"id": "all-MiniLM-L6-v2", "dimensions": 384, "description": "Fast, lightweight"},
            {"id": "all-mpnet-base-v2", "dimensions": 768, "description": "Higher quality"},
        ]
    }
