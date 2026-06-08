"""
Module ingestion — pipeline de traitement de documents vers Qdrant.
Chunking AST-aware pour le code, RecursiveCharacterTextSplitter pour les docs.
"""
from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from sentence_transformers import SentenceTransformer
import os, uuid, datetime

router = APIRouter()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "forge_knowledge"

CODE_EXTENSIONS = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs"}


def get_qdrant() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


def get_model() -> SentenceTransformer:
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def chunk_text(text: str, file_path: str) -> List[str]:
    """
    Chunking adaptatif :
    - Code : séparateurs respectant les frontières de fonctions/classes
    - Texte : séparateurs sémantiques standards
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in CODE_EXTENSIONS:
        separators = ["\nclass ", "\ndef ", "\nasync def ", "\nfunction ", "\nconst ", "\n\n", "\n"]
    else:
        separators = ["\n\n", "\n", ". ", " "]

    splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=512,
        chunk_overlap=64,
    )
    return splitter.split_text(text)


class IngestRequest(BaseModel):
    text: str
    file_path: str
    project_name: str
    file_type: Optional[str] = None


class IngestResponse(BaseModel):
    chunks_inserted: int
    file_path: str


@router.post("/", response_model=IngestResponse)
def ingest(req: IngestRequest):
    """Ingère un document dans Qdrant (chunking + embedding + stockage)."""
    qdrant = get_qdrant()
    model = get_model()

    # S'assurer que la collection existe
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION not in collections:
        qdrant.create_collection(
            COLLECTION,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

    chunks = chunk_text(req.text, req.file_path)
    if not chunks:
        return IngestResponse(chunks_inserted=0, file_path=req.file_path)

    vectors = model.encode(chunks, normalize_embeddings=True).tolist()
    timestamp = datetime.datetime.utcnow().isoformat()

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "text": chunk,
                "file_path": req.file_path,
                "project_name": req.project_name,
                "file_type": req.file_type or os.path.splitext(req.file_path)[1],
                "timestamp": timestamp,
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]

    qdrant.upsert(collection_name=COLLECTION, points=points)

    return IngestResponse(chunks_inserted=len(points), file_path=req.file_path)


@router.delete("/project/{project_name}")
def delete_project(project_name: str):
    """Supprime tous les chunks d'un projet de Qdrant."""
    qdrant = get_qdrant()
    qdrant.delete(
        collection_name=COLLECTION,
        points_selector={"filter": {"must": [{"key": "project_name", "match": {"value": project_name}}]}},
    )
    return {"deleted": True, "project": project_name}
