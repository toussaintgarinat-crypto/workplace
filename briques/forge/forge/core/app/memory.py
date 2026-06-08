"""Module mémoire / RAG — portage de memory/*.ts (S129), SANS Vercel AI SDK.

Réplique le pipeline du Bun :
- une collection Qdrant **par provider d'embedding** (forge_local/openai/gemini/mistral) ;
- embeddings **locaux** via le ML module (fastembed, 384-dim, toujours dispo) et
  **API** (openai/gemini/mistral) routés par la **LiteLLM Gateway** (OpenAI-compatible,
  remplace `embed` du Vercel AI SDK) — dispo = clé provider présente ;
- ``ingest``/``delete_by_source`` (chunking 512/overlap 64, embed sur tous les
  providers dispo) ;
- ``get_context`` : recherche sémantique Qdrant (tri score+récence) + enrichissement
  **brique Mémoire Workplace** opt-in (contrat /rappeler, port 5600).

Tout best-effort : si Qdrant/ML/Mémoire indisponible, on dégrade vers "" sans lever.

Mémoire Workplace (S-memoire) : remplace MemPalace. Au lieu d'un client opt-in
authentifié par token (``/api/search``, métaphore wing/room), forge consulte la
**brique Mémoire** via son contrat simple et sans token — la même façon que le
noyau Workplace : ``GET /rappeler`` (lecture) et ``POST /retenir`` (écriture). La
brique encapsule espaces, JWT et le projet Memory (graphe IPCRa / pgvector).
"""

from __future__ import annotations

import datetime
import logging
import uuid as uuidlib

import httpx
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.config import settings

logger = logging.getLogger(__name__)

# Une collection par provider d'embedding (identique au Bun memory/index.ts).
COLLECTIONS: dict[str, dict] = {
    "local": {"name": "forge_local", "size": 384},
    "openai": {"name": "forge_openai", "size": 1536},
    "gemini": {"name": "forge_gemini", "size": 768},
    "mistral": {"name": "forge_mistral", "size": 1024},
}

# provider d'embedding API → modèle gateway (LiteLLM, OpenAI-compatible /embeddings).
_EMBED_MODELS = {
    "openai": "text-embedding-3-small",
    "gemini": "text-embedding-004",
    "mistral": "mistral-embed",
}
_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

_qdrant: AsyncQdrantClient | None = None


def _client() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
        )
    return _qdrant


# ── Disponibilité providers (parité embedder.ts) ────────────────────────
def _is_available(provider: str) -> bool:
    if provider == "local":
        return True
    return bool(getattr(settings, _PROVIDER_KEYS[provider], ""))


def available_providers() -> list[str]:
    return [p for p in COLLECTIONS if _is_available(p)]


def resolve_provider(preferred: str | None = None) -> str:
    """Préféré si dispo, sinon priorité openai > gemini > mistral > local."""
    if preferred and _is_available(preferred):
        return preferred
    for p in ("openai", "gemini", "mistral", "local"):
        if _is_available(p):
            return p
    return "local"


# ── Embeddings ──────────────────────────────────────────────────────────
async def _embed_local(texts: list[str]) -> list[list[float]]:
    """Embeddings 384-dim via la **Gateway Workplace** (modèle all-minilm, Ollama).

    Workplace S17 (décision S17-5) : on réutilise l'unique moteur d'embeddings de
    la Gateway — le même que la brique Mémoire — au lieu de réveiller le ml-module
    torch de Forge (sous-système redondant). La collection ``forge_local`` reste en
    384 dims, donc compatible avec l'existant. La Gateway est OpenAI-compatible, on
    réutilise le même client que les providers API.
    """
    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)
    resp = await client.embeddings.create(model=settings.LOCAL_EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


async def _embed_api(texts: list[str], provider: str) -> list[list[float]]:
    client = AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)
    resp = await client.embeddings.create(model=_EMBED_MODELS[provider], input=texts)
    return [d.embedding for d in resp.data]


async def _embed_batch(texts: list[str], provider: str) -> list[list[float]]:
    if provider == "local":
        return await _embed_local(texts)
    return await _embed_api(texts, provider)


async def embed_one(text: str, provider: str) -> tuple[list[float], str]:
    """→ (vecteur, nom de collection) pour le provider donné."""
    vecs = await _embed_batch([text], provider)
    return vecs[0], COLLECTIONS[provider]["name"]


# ── Ingestion ───────────────────────────────────────────────────────────
def chunk_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_SIZE])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if len(c.strip()) > 20]


async def _ensure_collection(name: str, size: int) -> None:
    client = _client()
    if not await client.collection_exists(name):
        await client.create_collection(
            name, vectors_config=qm.VectorParams(size=size, distance=qm.Distance.COSINE)
        )


async def ingest(
    text: str,
    source_id: str,
    source_type: str,
    user_id: str,
    pole_id: str | None = None,
    title: str | None = None,
) -> dict[str, int]:
    """Ingère un document dans Qdrant avec tous les providers dispo. Best-effort."""
    chunks = chunk_text(text)
    counts = {"local": 0, "openai": 0, "gemini": 0, "mistral": 0}
    if not chunks:
        return counts

    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    for provider in available_providers():
        try:
            vecs = await _embed_batch(chunks, provider)
            coll = COLLECTIONS[provider]
            await _ensure_collection(coll["name"], coll["size"])
            points = [
                qm.PointStruct(
                    id=str(uuidlib.uuid4()),
                    vector=vecs[i],
                    payload={
                        "text": chunk,
                        "source_id": source_id,
                        "source_type": source_type,
                        "user_id": user_id,
                        "pole_id": pole_id,
                        "title": title or "",
                        "timestamp": timestamp,
                        "provider": provider,
                    },
                )
                for i, chunk in enumerate(chunks)
            ]
            await _client().upsert(coll["name"], points=points)
            counts[provider] = len(points)
        except Exception as e:  # noqa: BLE001 — un provider qui échoue n'arrête pas les autres
            logger.warning("[forge:ingestor] %s embedding/upsert failed: %s", provider, str(e)[:120])

    # Écriture mémoire Workplace (opt-in, best-effort) : le RAG chunké reste dans
    # Qdrant, mais le document est aussi retenu comme un souvenir « ressource »
    # consultable par tout Workplace via la brique Mémoire.
    await mem_retenir(text, titre=title or source_type, type_="ressource")
    return counts


async def delete_by_source(source_id: str) -> None:
    for coll in COLLECTIONS.values():
        try:
            await _client().delete(
                coll["name"],
                points_selector=qm.FilterSelector(filter=qm.Filter(
                    must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
                )),
            )
        except Exception:  # noqa: BLE001 — silencieux si collection vide/absente
            pass


async def delete_by_user(user_id: str) -> dict[str, str]:
    """RGPD (S18-5) — efface tous les vecteurs d'un utilisateur dans Qdrant.

    Les points portent ``payload.user_id`` (cf. ``ingest``). On supprime par filtre
    sur ce champ dans **toutes** les collections d'embedding. Best-effort par
    collection : renvoie un statut par collection (``ok`` / ``absente`` / message).
    """
    out: dict[str, str] = {}
    for coll in COLLECTIONS.values():
        name = coll["name"]
        try:
            if not await _client().collection_exists(name):
                out[name] = "absente"
                continue
            await _client().delete(
                name,
                points_selector=qm.FilterSelector(filter=qm.Filter(
                    must=[qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))]
                )),
            )
            out[name] = "ok"
        except Exception as e:  # noqa: BLE001
            out[name] = f"erreur: {str(e)[:80]}"
    return out


async def mem_forget_user(user_id: str, espace: str | None = None) -> dict | None:
    """RGPD (S18-5) — demande à la brique Mémoire d'oublier les souvenirs d'un sujet.

    ⚠️ **Limite honnête** : la brique Mémoire n'expose côté Workplace que ``/retenir``
    et ``/rappeler``. Les souvenirs écrits par Forge (``mem_retenir``) le sont dans un
    **espace partagé** sans ``user_id`` → ils ne sont pas attribuables à un sujet, donc
    pas effaçables sélectivement aujourd'hui. Cette fonction tente un contrat ``/oublier``
    si la brique l'implémente, et retourne ``None`` sinon (jamais bloquant). Un effacement
    réel côté Mémoire nécessite : (1) un contrat ``/oublier`` sur la brique, (2) le
    marquage ``user_id``/``espace`` à l'écriture. Cf. S18-5 (gap inter-brique).
    """
    if not _mem_enabled():
        return None
    try:
        corps: dict = {"user_id": user_id}
        esp = espace or settings.MEMOIRE_ESPACE
        if esp:
            corps["espace"] = esp
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_mem_base()}/oublier", json=corps)
        if r.status_code == 404:
            return {"statut": "non_supporté", "detail": "brique Mémoire sans contrat /oublier"}
        return r.json() if r.status_code < 400 else {"statut": "erreur", "code": r.status_code}
    except Exception:  # noqa: BLE001
        return None


# ── Recherche / contexte (retriever.ts) ─────────────────────────────────
async def _qdrant_search(question: str, limit: int, min_score: float, pole_id: str | None,
                         provider: str | None) -> str:
    try:
        prov = resolve_provider(provider)
        vector, collection = await embed_one(question, prov)
        flt = None
        if pole_id:
            flt = qm.Filter(must=[qm.FieldCondition(key="pole_id", match=qm.MatchValue(value=pole_id))])
        results = await _client().search(
            collection, query_vector=vector, limit=limit, with_payload=True, query_filter=flt
        )
        relevant = [r for r in results if r.score > min_score]
        if not relevant:
            return ""

        def _rank(r):
            ts = (r.payload or {}).get("timestamp") or 0
            try:
                t = datetime.datetime.fromisoformat(str(ts).replace("Z", "")).timestamp() if ts else 0
            except (ValueError, TypeError):
                t = 0
            return r.score * 0.7 + (t / 1e12) * 0.3

        relevant.sort(key=_rank, reverse=True)
        return "\n\n---\n\n".join(
            f"[{(r.payload or {}).get('title') or (r.payload or {}).get('source_type') or 'doc'}]\n"
            f"{(r.payload or {}).get('text')}"
            for r in relevant
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[forge:retriever] RAG failed: %s", str(e)[:120])
        return ""


async def get_context(question: str, _session_id: str, limit: int = 5, min_score: float = 0.65,
                      pole_id: str | None = None, provider: str | None = None) -> str:
    """Recherche sémantique Qdrant + enrichissement brique Mémoire Workplace opt-in."""
    rag = await _qdrant_search(question, limit, min_score, pole_id, provider)
    hits = await mem_prefetch(question, 3)
    return rag + mem_format_context(hits)


# ── Client brique Mémoire Workplace (contrat /rappeler + /retenir) — opt-in ──
def _mem_enabled() -> bool:
    return bool(settings.MEMOIRE_URL)


def _mem_base() -> str:
    return settings.MEMOIRE_URL.rstrip("/")


async def mem_prefetch(query: str, n: int = 5, espace: str | None = None) -> list[dict]:
    """Lecture : consulte la brique Mémoire (GET /rappeler, recherche hybride).

    La brique renvoie ``{souvenirs:[{id,titre,extrait,type}]}`` (pas de score : le
    tri/seuil pertinence est déjà fait côté projet Memory). Best-effort → [] si KO.
    """
    if not _mem_enabled():
        return []
    try:
        params: dict = {"q": query, "limite": n}
        esp = espace or settings.MEMOIRE_ESPACE
        if esp:
            params["espace"] = esp
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_mem_base()}/rappeler", params=params)
        if r.status_code != 200:
            return []
        return r.json().get("souvenirs", [])
    except Exception:  # noqa: BLE001
        return []


def mem_format_context(hits: list[dict]) -> str:
    if not hits:
        return ""
    blocks = []
    for h in hits:
        extrait = h.get("extrait", "")
        snippet = extrait[:450] + "…" if len(extrait) > 450 else extrait
        titre = h.get("titre") or h.get("type") or "souvenir"
        blocks.append(f"[{titre} · {h.get('type', '?')}]\n{snippet}")
    return "\n\n## Mémoires Workplace\n" + "\n\n---\n\n".join(blocks)


async def mem_retenir(contenu: str, titre: str | None = None, type_: str = "ressource",
                      espace: str | None = None) -> dict | None:
    """Écriture : mémorise un savoir dans la brique Mémoire (POST /retenir).

    Best-effort → None si la brique est désactivée ou injoignable (jamais bloquant).
    """
    if not _mem_enabled():
        return None
    try:
        corps: dict = {"contenu": contenu, "type": type_}
        if titre:
            corps["titre"] = titre
        esp = espace or settings.MEMOIRE_ESPACE
        if esp:
            corps["espace"] = esp
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_mem_base()}/retenir", json=corps)
        return r.json() if r.status_code < 400 else None
    except Exception:  # noqa: BLE001
        return None
