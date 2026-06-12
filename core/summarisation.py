"""Summarization à froid de l'historique (Sprint S138, chantier 3b).

Le trimming pur (`trimming.py`) coupe la fenêtre : rapide, mais il *perd* les vieux
messages. Quand une conversation d'agent devient longue, on préfère **condenser**
l'historique ancien en un résumé compact (via un petit modèle bon marché) plutôt
que de le jeter — on garde les faits/décisions sans payer tous les tokens.

Appelé en PREMIER dans `llm_pipeline.completer()` (crochet `# [S138-3b]`), avant le
trim. N'importe PAS `llm_pipeline` (cycle) : il fait son propre appel Gateway.

Sécurités :
  - les messages `system` et ceux marqués `pinned=True` sont gardés INTACTS ;
  - on ne condense que le « milieu » (au-delà des N derniers tours) ;
  - tout échec (modèle indisponible…) → on renvoie l'historique inchangé ;
  - le coût du résumé est lui-même journalisé (étiquette « resume »).
"""

import logging
import os

import httpx

import journal_usage
import langue as langue_mod
import trimming

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.environ["GATEWAY_KEY"]  # requis — défini dans le .env racine (plus de défaut public)

SEUIL_DEFAUT = int(os.getenv("RESUME_SEUIL_TOKENS", "3000"))   # en deçà : on ne fait rien
GARDER_DEFAUT = int(os.getenv("RESUME_GARDER", "6"))           # derniers tours intacts

def _prompt(langue=None) -> str:
    """Prompt de condensation, rédigé dans la langue du Jarvis (S39, défaut `fr`)."""
    return (
        "Tu es un assistant qui CONDENSE un historique de conversation. Résume les "
        f"échanges ci-dessous {langue_mod.consigne_resume(langue)}, en une note compacte "
        "qui PRÉSERVE : les faits établis, les décisions prises, les identifiants/noms "
        "cités, et les tâches en cours. Pas de bavardage, pas de salutations. Va à "
        "l'essentiel."
    )


def _modele_resume(conf: dict) -> str | None:
    """Modèle du résumé : réglage explicite, sinon un `free/*`/`ollama` des fallbacks,
    sinon le modèle courant (dernier recours)."""
    explicite = (conf.get("modele_resume") or "").strip()
    if explicite:
        return explicite
    for m in conf.get("fallback_models", []):
        if m.startswith("free/") or m.startswith("ollama/"):
            return m
    return conf.get("model")


async def condenser(client: httpx.AsyncClient, messages: list[dict], conf: dict) -> list[dict]:
    """Renvoie un historique condensé si nécessaire, sinon l'historique d'origine."""
    seuil = int(conf.get("seuil_resume_tokens") or SEUIL_DEFAUT)
    garder = int(conf.get("resume_garder") or GARDER_DEFAUT)
    if trimming.estimer_tokens(messages) <= seuil:
        return messages

    systeme = [m for m in messages if m.get("role") == "system" or m.get("pinned")]
    autres = [m for m in messages if not (m.get("role") == "system" or m.get("pinned"))]
    if len(autres) <= garder + 2:        # trop peu d'ancien à condenser : on laisse
        return messages

    anciens, recents = autres[:-garder], autres[-garder:]
    # Ne pas ouvrir la fenêtre « récents » sur un message `tool` orphelin.
    while recents and recents[0].get("role") == "tool":
        anciens, recents = anciens + recents[:1], recents[1:]

    a_resumer = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in anciens
                          if isinstance(m.get("content"), str))
    if not a_resumer.strip():
        return messages

    modele = _modele_resume(conf)
    if not modele:
        return messages
    try:
        r = await client.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
            json={"model": modele, "temperature": 0,
                  "messages": [{"role": "system", "content": _prompt(conf.get("langue"))},
                               {"role": "user", "content": a_resumer[:12000]}]},
        )
        if r.status_code >= 400:
            logger.warning("Résumé : Gateway %s sur %s — historique gardé tel quel",
                           r.status_code, modele)
            return messages
        corps = r.json()
        resume = corps["choices"][0]["message"].get("content") or ""
        usage = corps.get("usage") or {}
        journal_usage.enregistrer(
            modele=modele, etiquette="resume",
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            cout_usd=0)  # coût chiffré globalement ; le résumé vise un modèle gratuit
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("Résumé indisponible (%s) — historique gardé tel quel", e)
        return messages

    if not resume.strip():
        return messages
    note = {"role": "system",
            "content": "[Résumé du contexte antérieur, condensé pour économiser des "
                       "tokens]\n" + resume.strip()}
    return systeme + [note] + recents
