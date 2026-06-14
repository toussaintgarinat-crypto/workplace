"""Client Mémoire pour Oria — délègue à la brique Mémoire Workplace (port 5600).

Remplace l'ancien client MemPalace (palace externe ``localhost:8100`` + mode Qdrant
local + ``mempalace.knowledge_graph``). Désormais **une seule voie** : le contrat
HTTP simple de la brique Mémoire (``/retenir`` / ``/rappeler``), qui encapsule
espaces, JWT et le projet Memory (graphe IPCRa / pgvector).

Configuration : ``MEMOIRE_URL`` (ex. ``http://host.docker.internal:5600``). Vide →
mémoire **désactivée** : toutes les fonctions dégradent en ``[]`` / ``False`` / ``0``
sans jamais lever (comportement best-effort conservé).

Cloisonnement : chaque utilisateur a son espace mémoire « oria-user-<id> » ; à
défaut (pas d'``user_id``) l'espace solution de la brique. Tout ce qu'Oria écrit
porte la location ``wing_user`` + une salle thématique (ipcra-sessions / documents /
jardin-conversations) et un ``hall`` en métadonnée.

⚠️ Graphe de connaissances (``create_branch`` / ``merge_branch`` /
``check_contradictions``) : **no-ops honnêtes**. Ils l'étaient déjà en mode HTTP
(le KG n'a jamais été exposé par l'API, cf. ancien commentaire « not yet in API »),
et aucun router/worker ne les appelle (seuls les tests les patchent). La brique /
Memory pourra les implémenter plus tard sur son graphe d'arêtes natif.

Le nom du module reste ``mempalace_client`` pour ne pas toucher les 6 consommateurs
(``documents``/``jardin``/``ipcra``/``shared_zones``/``jobs_worker``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from config import config

# Le score de la brique (recherche hybride) est déjà rangé/limité côté Memory ;
# on n'applique donc pas de coupe client agressive (l'ancien seuil cosinus 0.35
# valait pour le mode Qdrant local, retiré). On expose le score tel quel.
_TIMEOUT = 8.0


def _base() -> str:
    return config.MEMOIRE_URL


def _enabled() -> bool:
    return bool(_base())


def _espace(user_id: str | None) -> str | None:
    """Espace mémoire par utilisateur (cloisonnement). None → espace solution brique."""
    return f"oria-user-{user_id}" if user_id else None


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _retenir(contenu: str, *, titre: str, room: str, hall: str,
             metadata: dict, user_id: str | None) -> bool:
    """Écrit un souvenir via la brique. Best-effort → False si désactivée/KO."""
    if not _enabled() or not (contenu or "").strip():
        return False
    corps: dict[str, Any] = {
        "contenu": contenu,
        "titre": titre,
        "type": "input",          # tout ce qu'Oria capte est une entrée IPCRa
        "wing": "wing_user",      # location.wing côté Memory
        "room": room,
        "hall": hall,
        "metadata": metadata or {},
    }
    esp = _espace(user_id)
    if esp:
        corps["espace"] = esp
    try:
        r = httpx.post(f"{_base()}/retenir", json=corps, timeout=_TIMEOUT)
        return r.status_code < 400
    except Exception:
        return False


def _chunk(content: str, taille: int = 800, maxi: int = 30) -> list[str]:
    """Découpe par paragraphes en fenêtres ~`taille` caractères (parité historique)."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > taille and current:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks[:maxi]


# ── API publique (signatures inchangées vs l'ancien client) ──────────────────

def prefetch(query: str, n: int = 5, wing: str | None = None, user_id: str | None = None) -> list:
    """Souvenirs pertinents pour `query` → [{text, wing, room, similarity}] ou [].

    `wing` est accepté pour compatibilité mais n'est plus un filtre dur : la brique
    range et limite déjà par pertinence (recherche hybride), et l'espace par
    utilisateur cloisonne déjà les résultats. Best-effort → [] si indispo.
    """
    if not _enabled():
        return []
    try:
        params: dict[str, Any] = {"q": query, "limite": n}
        esp = _espace(user_id)
        if esp:
            params["espace"] = esp
        r = httpx.get(f"{_base()}/rappeler", params=params, timeout=_TIMEOUT)
        if r.status_code != 200:
            return []
        souvenirs = r.json().get("souvenirs", [])
    except Exception:
        return []
    return [
        {
            "text": s.get("extrait", ""),
            "wing": "wing_user",
            "room": s.get("type", "?"),
            "similarity": round(s.get("score", 0) or 0, 3),
        }
        for s in souvenirs
    ]


def sync(content: str, session_id: str, phase: str, titre: str, user_id: str | None = None) -> bool:
    """Persiste une catégorie IPCRa dans la mémoire de l'utilisateur."""
    return _retenir(
        content,
        titre=(titre or phase or "session").strip(),
        room="ipcra-sessions",
        hall="hall_events",
        metadata={
            "source_file": f"ipcra/{session_id}/{phase}",
            "date": _today(),
            "added_by": "oria-ipcra",
            "session_titre": titre,
            "phase": phase,
        },
        user_id=user_id,
    )


def sync_document(
    content: str,
    doc_id: str,
    doc_name: str,
    owner_id: str,
    session_id: str | None = None,
    session_titre: str | None = None,
    user_id: str | None = None,
) -> int:
    """Indexe un document par chunks dans la mémoire. Retourne le nombre de chunks écrits."""
    if not _enabled() or not content.strip():
        return 0
    chunks = _chunk(content)
    base_meta = {
        "source_file": doc_name,
        "date": _today(),
        "added_by": "oria-markitdown",
        "doc_id": doc_id,
        "owner_id": owner_id,
        **({"session_id": session_id} if session_id else {}),
        **({"session_titre": session_titre} if session_titre else {}),
    }
    # Le document appartient à `owner_id` ; on scope son espace mémoire dessus.
    espace_user = user_id or owner_id
    added = 0
    for i, chunk in enumerate(chunks):
        meta = {**base_meta, "chunk_index": i}
        if _retenir(chunk, titre=f"{doc_name} ({i + 1})", room="documents",
                    hall="hall_facts", metadata=meta, user_id=espace_user):
            added += 1
    return added


def sync_conversation_turn(user_message: str, assistant_response: str, user_id: str) -> bool:
    """Persiste un échange Q/R dans la mémoire personnelle de l'utilisateur."""
    content = f"Utilisateur : {user_message}"
    if assistant_response:
        content += f"\n\nAssistant : {assistant_response}"
    return _retenir(
        content,
        titre=user_message[:60] or "échange",
        room="jardin-conversations",
        hall="hall_events",
        metadata={"date": _today(), "added_by": "oria-jardin"},
        user_id=user_id,
    )


def format_context_block(hits: list) -> str:
    """Formate les souvenirs récupérés en bloc Markdown pour le system prompt."""
    if not hits:
        return ""
    lines = []
    for h in hits:
        snippet = (h.get("text") or "")[:450].strip()
        if len(h.get("text") or "") > 450:
            snippet += "…"
        lines.append(f"[{h.get('wing', '?')}/{h.get('room', '?')} · similarité {h.get('similarity', 0)}]\n{snippet}")
    return "\n\n## Mémoires pertinentes (Mémoire Workplace)\n" + "\n\n---\n\n".join(lines)


# ── Graphe de connaissances — no-ops honnêtes (non exposé par la brique) ──────

def create_branch(session_id: str) -> bool:
    return False


def merge_branch(session_id: str) -> dict:
    return {"merged": 0, "conflicts": []}


def check_contradictions(session_id: str) -> list:
    return []
