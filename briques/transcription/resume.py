"""Synthèse d'une transcription en NOTES de réunion via l'« économe gratuit » (≈0 $).

Même esprit que le briefing S30 : un modèle GRATUIT en tête (coût ~0). La brique reste
AUTONOME — elle ne dépend pas du noyau : elle appelle directement la Gateway Workplace en
HTTP (proxy OpenAI-compatible), comme le fait le fournisseur `gateway` de la brique vidéo.

Repli HONNÊTE : sans `GATEWAY_KEY`, ou si l'appel échoue / rend un JSON illisible, on
retombe sur `prompts.repli_heuristique` (premières phrases, marqué `source: heuristique`).
On ne fait jamais passer une heuristique pour une synthèse LLM.
"""
import json
import os
import re
from typing import Optional

import httpx

import prompts


def _gateway_url() -> str:
    return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001").rstrip("/")


def disponible() -> bool:
    """La synthèse LLM est-elle possible (clé Gateway présente) ? — sync, sans réseau."""
    return bool(os.getenv("GATEWAY_KEY"))


def _extraire_json(contenu: str) -> Optional[dict]:
    """Parse une réponse LLM en JSON, en tolérant des ```fences``` ou du texte autour."""
    contenu = (contenu or "").strip()
    if not contenu:
        return None
    try:
        return json.loads(contenu)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", contenu, re.DOTALL)   # premier objet { ... } trouvé
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _normaliser(brut: dict) -> dict:
    """Garantit la forme attendue (clés présentes, listes = listes), source = llm."""
    def liste(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return [str(v).strip()] if v else []
    return {
        "resume": str(brut.get("resume") or "").strip(),
        "points_action": liste(brut.get("points_action")),
        "themes": liste(brut.get("themes")),
        "decisions": liste(brut.get("decisions")),
        "source": "llm",
    }


async def resumer(texte: str, langue: Optional[str] = None) -> dict:
    """Transcription → {resume, points_action, themes, decisions, source}.

    `langue` = langue de SORTIE des notes (peut différer de la langue de l'audio).
    Sans Gateway ou en cas d'échec : repli heuristique honnête (source: heuristique).
    """
    texte = (texte or "").strip()
    if not texte:
        return {"resume": "", "points_action": [], "themes": [], "decisions": [],
                "source": "vide"}

    if not disponible():
        return prompts.repli_heuristique(texte)

    modele = os.getenv("TRANSCRIPTION_RESUME_MODEL", "free/google/gemma-4-31b-it")
    body = {
        "model": modele,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": prompts.prompt_resume(langue)},
            {"role": "user", "content": "TRANSCRIPTION :\n" + texte[:24000]},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{_gateway_url()}/v1/chat/completions",
                             headers={"Authorization": f"Bearer {os.getenv('GATEWAY_KEY')}"},
                             json=body)
            r.raise_for_status()
            contenu = r.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 — Gateway absente/injoignable : repli honnête
        return prompts.repli_heuristique(texte)

    brut = _extraire_json(contenu)
    if not brut:
        return prompts.repli_heuristique(texte)
    return _normaliser(brut)
