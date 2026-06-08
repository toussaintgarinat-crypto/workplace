"""Shadow routing : A/B coût vs qualité (Sprint S138, chantier 4).

Comment prouver qu'un flux peut passer sur un modèle `free/*` sans casser la
qualité ? Sur un **échantillon** d'appels (5 % par défaut), une fois la réponse de
prod servie, on rejoue la requête **en tâche de fond** vers un candidat moins cher
(100 % asynchrone : ni la latence ni la réponse vue par l'utilisateur ne changent),
puis on compare les deux réponses par **similarité d'embedding**. Le verdict agrégé
alimente une recommandation : « ce flux est équivalent à X % → rétrogradable ».

Adaptation Workplace : journal **fichier** (`/data/shadow_runs.jsonl`), embeddings
via la Gateway (réutilise `cache_semantique`). N'importe PAS `llm_pipeline` (cycle) :
coût lu sur l'en-tête LiteLLM du candidat (un `free/*` coûte 0).
"""

import asyncio
import json
import logging
import os
import random
import threading
import time
from pathlib import Path

import httpx

import cache_semantique
import journal_usage

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.environ["GATEWAY_KEY"]  # requis — défini dans le .env racine (plus de défaut public)

SHADOW_PATH = Path(os.getenv("SHADOW_RUNS_PATH", "/data/shadow_runs.jsonl"))
TAUX_DEFAUT = float(os.getenv("SHADOW_TAUX", "0.05"))
SEUIL_EQUIV = float(os.getenv("SHADOW_SEUIL_EQUIV", "0.90"))   # ≥ → « équivalent »

_verrou = threading.Lock()


def echantillonne(conf: dict) -> bool:
    """True si le shadow est actif ET que ce tirage tombe dans l'échantillon."""
    if not conf.get("shadow_actif"):
        return False
    taux = float(conf.get("shadow_taux") or TAUX_DEFAUT)
    return random.random() < max(0.0, min(1.0, taux))


def candidat(conf: dict, modele_prod: str) -> str | None:
    """Modèle candidat moins cher : réglage explicite, sinon 1er `free/*`/`ollama`
    des fallbacks. Jamais le modèle de prod lui-même."""
    explicite = (conf.get("shadow_candidat") or "").strip()
    if explicite and explicite != modele_prod:
        return explicite
    for m in conf.get("fallback_models", []):
        if (m.startswith("free/") or m.startswith("ollama/")) and m != modele_prod:
            return m
    return None


def planifier(messages, conf, reponse_prod, modele_prod, cout_prod, etiquette) -> bool:
    """Lance la comparaison en tâche de fond si une boucle asyncio tourne. Renvoie
    True si planifié. Fire-and-forget : n'attend rien, ne bloque pas la prod."""
    try:
        boucle = asyncio.get_running_loop()
    except RuntimeError:
        return False
    boucle.create_task(comparer(messages, conf, reponse_prod, modele_prod,
                                cout_prod, etiquette))
    return True


async def comparer(messages, conf, reponse_prod, modele_prod, cout_prod, etiquette) -> None:
    """Rejoue la requête vers le candidat, compare et journalise. Ne lève jamais."""
    cible = candidat(conf, modele_prod)
    if not cible:
        return
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # On rejoue SANS outils (comparaison sur la génération de texte).
            sans_outils = [m for m in messages if m.get("role") != "tool"]
            r = await client.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
                json={"model": cible, "temperature": 0, "messages": sans_outils},
            )
            if r.status_code >= 400:
                logger.warning("Shadow : candidat %s a répondu %s", cible, r.status_code)
                return
            corps = r.json()
            reponse_cand = corps["choices"][0]["message"].get("content") or ""
            cout_cand = _cout_entete(r.headers.get("x-litellm-response-cost"), cible)
            equiv = await _equivalence(client, reponse_prod, reponse_cand)
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Shadow indisponible (%s)", e)
        return

    if equiv is None:
        return
    verdict = "equivalent" if equiv >= SEUIL_EQUIV else "different"
    _ajouter({
        "ts": time.time(),
        "etiquette": etiquette,
        "modele_prod": modele_prod,
        "modele_candidat": cible,
        "equiv_score": round(equiv, 4),
        "cout_prod": round(cout_prod or 0, 6),
        "cout_candidat": round(cout_cand or 0, 6),
        "verdict": verdict,
    })


def _cout_entete(entete: str | None, modele: str) -> float:
    if entete:
        try:
            return max(0.0, float(entete))
        except (TypeError, ValueError):
            pass
    return 0.0  # candidat free/local : coût nul par défaut


async def _equivalence(client, a: str, b: str) -> float | None:
    """Similarité cosinus des embeddings des deux réponses (None si indisponible)."""
    if not a.strip() or not b.strip():
        return 0.0
    va = await cache_semantique._embed(client, a)
    vb = await cache_semantique._embed(client, b)
    if va is None or vb is None:
        return None
    return cache_semantique._cosine(va, vb)


def _ajouter(ligne: dict) -> None:
    try:
        with _verrou:
            SHADOW_PATH.parent.mkdir(parents=True, exist_ok=True)
            with SHADOW_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Shadow non écrit : %s", e)


def _lignes() -> list[dict]:
    if not SHADOW_PATH.exists():
        return []
    out = []
    try:
        with SHADOW_PATH.open(encoding="utf-8") as f:
            for brute in f:
                brute = brute.strip()
                if brute:
                    try:
                        out.append(json.loads(brute))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return out


def rapport() -> dict:
    """Agrégat par (étiquette, prod→candidat) : score d'équivalence moyen, taux
    d'équivalence, et économie projetée si on rétrogradait ce flux."""
    par_flux: dict[str, dict] = {}
    for l in _lignes():
        cle = f"{l.get('etiquette')}:{l.get('modele_prod')}→{l.get('modele_candidat')}"
        g = par_flux.setdefault(cle, {"n": 0, "somme_equiv": 0.0, "equivalents": 0,
                                      "economie_usd": 0.0})
        g["n"] += 1
        g["somme_equiv"] += l.get("equiv_score", 0)
        g["equivalents"] += 1 if l.get("verdict") == "equivalent" else 0
        g["economie_usd"] += (l.get("cout_prod", 0) - l.get("cout_candidat", 0))

    flux = []
    for cle, g in par_flux.items():
        n = g["n"] or 1
        taux = g["equivalents"] / n
        flux.append({
            "flux": cle,
            "echantillons": g["n"],
            "equivalence_moyenne": round(g["somme_equiv"] / n, 3),
            "taux_equivalent": round(taux, 3),
            "economie_observee_usd": round(g["economie_usd"], 4),
            # Recommandation sûre : ≥ 20 échantillons et ≥ 90 % d'équivalence.
            "recommande_retrograder": g["n"] >= 20 and taux >= 0.90,
        })
    flux.sort(key=lambda x: x["taux_equivalent"], reverse=True)
    return {"flux": flux, "total_echantillons": sum(f["echantillons"] for f in flux)}
