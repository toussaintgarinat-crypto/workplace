"""Cache sémantique des réponses LLM (Sprint S138, chantier 2).

Beaucoup d'appels se répètent à l'identique ou presque (classement de documents
du même type, prompts système stables…). Plutôt que de repayer le modèle, on
renvoie la réponse déjà obtenue pour un prompt **sémantiquement équivalent**.

Adaptation Workplace (≠ workspace/forge qui visait pgvector dédié) : le Cœur n'a
pas de base SQL et la brique mémoire possède son propre Postgres (qu'on ne pille
pas). On reste donc **fichier** comme `journal_usage` :
  - embedding du prompt via la Gateway (`embedding/all-minilm`, 384 dims, gratuit, local) ;
  - entrées stockées en JSONL (`/data/llm_cache.jsonl`) ;
  - similarité **cosinus en Python pur** (pas de numpy : cache plafonné → quelques ms).

Garde-fous anti-faux-positif : hit seulement si `cosine ≥ SEUIL` (0.97 par défaut)
**et** même `scope_hash` (système + modèle + signature d'outils). TTL + plafond
d'entrées. Le cache est **opt-in par appel** (`cache=True`) et jamais utilisé pour
les tours à outils (effet de bord) ni les températures élevées — c'est l'appelant
qui décide (cf. `llm_pipeline.completer`).
"""

import hashlib
import json
import logging
import math
import os
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.environ["GATEWAY_KEY"]  # requis — défini dans le .env racine (plus de défaut public)
EMBEDDING_MODEL = os.getenv("LLM_CACHE_EMBEDDING", "embedding/all-minilm")

CACHE_PATH = Path(os.getenv("LLM_CACHE_PATH", "/data/llm_cache.jsonl"))
ACTIF = os.getenv("LLM_CACHE_ACTIF", "1").lower() not in ("0", "false", "no")
SEUIL = float(os.getenv("LLM_CACHE_SEUIL", "0.97"))
TTL_S = int(os.getenv("LLM_CACHE_TTL_S", str(7 * 24 * 3600)))   # 7 jours
MAX_ENTREES = int(os.getenv("LLM_CACHE_MAX", "2000"))

_verrou = threading.Lock()


def _texte_prompt(messages: list[dict]) -> str:
    """Concatène le contenu texte des messages → texte à embeder / normaliser."""
    bouts = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            bouts.append(f"{m.get('role', '?')}: {c.strip()}")
    return "\n".join(bouts)


def scope_hash(messages: list[dict], modele: str, tools: list[dict] | None) -> str:
    """Empreinte du *contexte d'appel* : système + modèle + signature d'outils.

    Un changement de prompt système ou d'outils invalide naturellement le cache
    (scope différent), sans purge explicite."""
    systeme = "".join(m.get("content") or "" for m in messages if m.get("role") == "system")
    noms_outils = sorted((t.get("function", {}) or {}).get("name", "") for t in (tools or []))
    brut = json.dumps([systeme, modele, noms_outils], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


async def _embed(client: httpx.AsyncClient, texte: str) -> list[float] | None:
    """Embedding via la Gateway. None si indisponible (le cache se désactive alors)."""
    try:
        r = await client.post(
            f"{GATEWAY_URL}/v1/embeddings",
            headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": texte[:8000]},
        )
        if r.status_code >= 400:
            logger.warning("Cache : embeddings Gateway %s", r.status_code)
            return None
        return r.json()["data"][0]["embedding"]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Cache : embeddings injoignables (%s)", e)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return -1.0
    ps = na = nb = 0.0
    for x, y in zip(a, b):
        ps += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return -1.0
    return ps / (math.sqrt(na) * math.sqrt(nb))


def _lignes() -> list[dict]:
    if not CACHE_PATH.exists():
        return []
    out = []
    try:
        with CACHE_PATH.open(encoding="utf-8") as f:
            for brute in f:
                brute = brute.strip()
                if brute:
                    try:
                        out.append(json.loads(brute))
                    except json.JSONDecodeError:
                        continue
    except OSError as e:
        logger.warning("Cache illisible : %s", e)
    return out


async def chercher(client: httpx.AsyncClient, messages: list[dict],
                   scope: str) -> dict | None:
    """Renvoie {'message', 'sim', 'modele'} si un voisin assez proche existe dans
    le même scope et non expiré, sinon None. Ne lève jamais."""
    if not ACTIF:
        return None
    vec = await _embed(client, _texte_prompt(messages))
    if vec is None:
        return None
    maintenant = time.time()
    meilleur, meilleure_sim = None, SEUIL
    for e in _lignes():
        if e.get("scope") != scope:
            continue
        if maintenant - e.get("ts", 0) > TTL_S:
            continue
        sim = _cosine(vec, e.get("embedding") or [])
        if sim >= meilleure_sim:
            meilleur, meilleure_sim = e, sim
    if meilleur is None:
        return None
    return {"message": meilleur["message"], "sim": round(meilleure_sim, 4),
            "modele": meilleur.get("modele")}


async def stocker(client: httpx.AsyncClient, messages: list[dict], scope: str,
                  message_reponse: dict, modele: str) -> None:
    """Mémorise (prompt → réponse) avec son embedding. Plafonne le fichier (FIFO).
    Ne lève jamais : un cache qui rate ne doit pas casser l'appel métier."""
    if not ACTIF:
        return
    vec = await _embed(client, _texte_prompt(messages))
    if vec is None:
        return
    entree = {
        "ts": time.time(),
        "scope": scope,
        "modele": modele,
        "prompt_norm": _texte_prompt(messages)[:500],
        "message": message_reponse,
        "embedding": vec,
    }
    try:
        with _verrou:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            lignes = _lignes()
            lignes.append(entree)
            if len(lignes) > MAX_ENTREES:           # FIFO : on jette les plus vieilles
                lignes = lignes[-MAX_ENTREES:]
            with CACHE_PATH.open("w", encoding="utf-8") as f:
                for l in lignes:
                    f.write(json.dumps(l, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Cache non écrit : %s", e)
