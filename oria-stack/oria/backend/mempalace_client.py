"""
Client MemPalace pour Oria — HTTP API (opt-in) avec fallback Python direct.

Mode HTTP  : définir MEMPALACE_API_URL + MEMPALACE_API_TOKEN
             → appelle l'API FastAPI MemPalace (port 8100 par défaut)
Mode local : si MEMPALACE_API_URL absent, utilise l'import Python direct (Qdrant local)

Dégradation gracieuse dans les deux modes : retourne [] / False sans lever d'exception.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────────
MEMPALACE_API_URL   = os.environ.get("MEMPALACE_API_URL", "").rstrip("/")
MEMPALACE_API_TOKEN = os.environ.get("MEMPALACE_API_TOKEN", "")

# Legacy — used when API URL is not set (Python direct mode)
PALACE_PATH = os.environ.get(
    "MEMPALACE_PALACE_PATH",
    str(Path.home() / ".mempalace" / "palace"),
)
PALACE_BASE_PATH = os.environ.get(
    "PALACE_BASE_PATH",
    str(Path.home() / ".mempalace" / "palaces"),
)
COLLECTION_NAME      = "mempalace_drawers"
SIMILARITY_THRESHOLD = 0.35

_HTTP_ENABLED = bool(MEMPALACE_API_URL and MEMPALACE_API_TOKEN)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {MEMPALACE_API_TOKEN}", "Content-Type": "application/json"}


def _http_search(query: str, n: int, wing: str | None) -> list[dict]:
    try:
        import httpx
        payload: dict[str, Any] = {"query": query, "n_results": n}
        if wing:
            payload["wing"] = wing
        r = httpx.post(
            f"{MEMPALACE_API_URL}/api/search",
            json=payload,
            headers=_headers(),
            timeout=8.0,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except Exception:
        return []


def _http_add_drawer(content: str, wing: str, room: str, metadata: dict | None = None) -> bool:
    try:
        import httpx
        r = httpx.post(
            f"{MEMPALACE_API_URL}/api/drawers",
            json={"content": content, "wing": wing, "room": room, "metadata": metadata or {}},
            headers=_headers(),
            timeout=8.0,
        )
        return r.status_code == 201
    except Exception:
        return False


# ── Legacy Python-direct helpers ──────────────────────────────────────────────

def _get_user_palace_path(user_id: str) -> str:
    return str(Path(PALACE_BASE_PATH) / user_id)


def _get_collection(palace_path: str | None = None, create: bool = False):
    path = palace_path or PALACE_PATH
    try:
        from mempalace.storage import get_palace_storage
        return get_palace_storage(path, create=create)
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def prefetch(query: str, n: int = 5, wing: str = None, user_id: str = None) -> list:
    """
    Cherche les souvenirs pertinents pour la requête.
    Retourne [{text, wing, room, similarity}] ou [] si inaccessible.
    """
    if _HTTP_ENABLED:
        raw = _http_search(query, n, wing)
        return [
            {
                "text":       r.get("content", ""),
                "wing":       r.get("metadata", {}).get("wing", "?"),
                "room":       r.get("metadata", {}).get("room", "?"),
                "similarity": r.get("score", 0),
            }
            for r in raw
            if r.get("score", 0) >= SIMILARITY_THRESHOLD
        ]

    # fallback: Python direct
    path = _get_user_palace_path(user_id) if user_id else None
    col  = _get_collection(path)
    if not col:
        return []
    try:
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results":   min(n, col.count() or 1),
            "include":     ["documents", "metadatas", "distances"],
        }
        if wing:
            kwargs["where"] = {"wing": wing}
        results = col.query(**kwargs)
        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            sim = round(1 - dist, 3)
            if sim >= SIMILARITY_THRESHOLD:
                hits.append({"text": doc, "wing": meta.get("wing", "?"), "room": meta.get("room", "?"), "similarity": sim})
        return hits
    except Exception:
        return []


def sync(content: str, session_id: str, phase: str, titre: str, user_id: str = None) -> bool:
    """Persiste le contenu d'une catégorie IPCRA dans MemPalace."""
    if not content.strip():
        return False

    metadata = {
        "source_file":    f"ipcra/{session_id}/{phase}",
        "date":           datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "added_by":       "oria-ipcra",
        "session_titre":  titre,
        "phase":          phase,
        "hall":           "hall_events",
    }

    if _HTTP_ENABLED:
        return _http_add_drawer(content, "wing_user", "ipcra-sessions", metadata)

    path = _get_user_palace_path(user_id) if user_id else None
    col  = _get_collection(path, create=True)
    if not col:
        return False
    try:
        uid       = hashlib.md5((content[:60] + datetime.now(timezone.utc).isoformat()).encode()).hexdigest()[:14]
        drawer_id = f"ipcra_{session_id}_{phase}_{uid}"
        col.add(ids=[drawer_id], documents=[content], metadatas=[{"wing": "wing_user", "room": "ipcra-sessions", **metadata}])
        return True
    except Exception:
        return False


def sync_document(
    content: str,
    doc_id: str,
    doc_name: str,
    owner_id: str,
    session_id: str = None,
    session_titre: str = None,
    user_id: str = None,
) -> int:
    """Indexe un document par chunks dans MemPalace. Retourne le nombre de chunks ajoutés."""
    if not content.strip():
        return 0

    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > 800 and current:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))

    added     = 0
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_meta = {
        "source_file": doc_name,
        "date":        date_str,
        "added_by":    "oria-markitdown",
        "doc_id":      doc_id,
        "owner_id":    owner_id,
        "hall":        "hall_facts",
        **({"session_id": session_id} if session_id else {}),
        **({"session_titre": session_titre} if session_titre else {}),
    }

    for i, chunk in enumerate(chunks[:30]):
        meta = {**base_meta, "chunk_index": i}
        if _HTTP_ENABLED:
            if _http_add_drawer(chunk, "wing_user", "documents", meta):
                added += 1
        else:
            path = _get_user_palace_path(user_id) if user_id else None
            col  = _get_collection(path, create=True)
            if not col:
                break
            try:
                uid = hashlib.md5(f"{doc_id}_{i}_{chunk[:30]}".encode()).hexdigest()[:12]
                col.add(
                    ids=[f"doc_{doc_id}_chunk{i}_{uid}"],
                    documents=[chunk],
                    metadatas=[{"wing": "wing_user", "room": "documents", **meta}],
                )
                added += 1
            except Exception:
                pass

    return added


def sync_conversation_turn(user_message: str, assistant_response: str, user_id: str) -> bool:
    """Persiste un échange Q/R dans le palace personnel."""
    content = f"Utilisateur : {user_message}"
    if assistant_response:
        content += f"\n\nAssistant : {assistant_response}"

    metadata = {
        "date":     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "added_by": "oria-jardin",
        "hall":     "hall_events",
    }

    if _HTTP_ENABLED:
        return _http_add_drawer(content, "wing_user", "jardin-conversations", metadata)

    path = _get_user_palace_path(user_id)
    col  = _get_collection(path, create=True)
    if not col:
        return False
    try:
        uid = hashlib.md5((content[:60] + datetime.now(timezone.utc).isoformat()).encode()).hexdigest()[:14]
        col.add(
            ids=[f"conv_{user_id}_{uid}"],
            documents=[content],
            metadatas=[{"wing": "wing_user", "room": "jardin-conversations", **metadata}],
        )
        return True
    except Exception:
        return False


def format_context_block(hits: list) -> str:
    """Formate les souvenirs récupérés en bloc Markdown pour le system prompt."""
    if not hits:
        return ""
    lines = []
    for h in hits:
        snippet = h["text"][:450].strip()
        if len(h["text"]) > 450:
            snippet += "…"
        lines.append(f"[{h['wing']}/{h['room']} · similarité {h['similarity']}]\n{snippet}")
    return "\n\n## Mémoires pertinentes (MemPalace)\n" + "\n\n---\n\n".join(lines)


# ── KnowledgeGraph — no-op when HTTP mode (not yet in API) ────────────────────

def _get_kg():
    if _HTTP_ENABLED:
        return None
    try:
        from mempalace.knowledge_graph import KnowledgeGraph
        return KnowledgeGraph()
    except Exception:
        return None


def create_branch(session_id: str) -> bool:
    kg = _get_kg()
    if not kg:
        return False
    try:
        kg.create_branch(f"ipcra_{session_id}")
        return True
    except Exception:
        return False


def merge_branch(session_id: str) -> dict:
    kg = _get_kg()
    if not kg:
        return {"merged": 0, "conflicts": []}
    try:
        branch_name = f"ipcra_{session_id}"
        conflicts   = kg.detect_contradictions(branch_name)
        merged      = kg.merge_branch(branch_name)
        return {"merged": merged, "conflicts": conflicts}
    except Exception:
        return {"merged": 0, "conflicts": []}


def check_contradictions(session_id: str) -> list:
    kg = _get_kg()
    if not kg:
        return []
    try:
        return kg.detect_contradictions(f"ipcra_{session_id}")
    except Exception:
        return []
