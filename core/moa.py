"""Mixture of Agents — conseil de modèles en parallèle avant les réponses complexes (S144).

Sur les requêtes marquées « complexes », N modèles du Gateway tournent en parallèle
sur le même contexte en rôle « conseiller analytique » (sans outils), puis un modèle
agrégateur synthétise leurs avis en une guidance privée injectée avant la réponse finale.
Opt-in : activé uniquement si `MOA_MODELES` est défini dans .env.
"""

import asyncio
import hashlib
import json
import logging
import os
from collections import OrderedDict
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)


class ConfigMOA(NamedTuple):
    modeles_reference: list[str]
    agregateur: str
    max_tokens_ref: int = 800
    temperature_ref: float = 0.4


def _depuis_env() -> "ConfigMOA | None":
    """Construit la config depuis MOA_MODELES et MOA_AGREGATEUR. None si absent."""
    brut = os.getenv("MOA_MODELES", "")
    if not brut.strip():
        return None
    modeles = [m.strip() for m in brut.split(",") if m.strip()]
    agregateur = os.getenv("MOA_AGREGATEUR", modeles[0] if modeles else "")
    return ConfigMOA(modeles_reference=modeles, agregateur=agregateur)


_MOTS_COMPLEXES_DEFAUT = {
    "planifie", "stratégie", "décide", "compare", "analyse", "choisir",
    "architecture", "implémente", "conception", "évaluer", "risque",
    "résume", "explique", "traduis", "décompose", "priorise", "propose",
    "liste", "crée", "optimise", "structure",
}


def _mots_complexes() -> set[str]:
    """Liste de mots-clés de complexité : défaut + MOA_MOTS_COMPLEXES (env, virgule-séparés)."""
    extra_brut = os.getenv("MOA_MOTS_COMPLEXES", "")
    extra = {m.strip().lower() for m in extra_brut.split(",") if m.strip()}
    return _MOTS_COMPLEXES_DEFAUT | extra


def est_complexe(message_utilisateur: str) -> bool:
    """Heuristique légère : longueur > 120 car OU mot-clé de complexité détecté."""
    msg = message_utilisateur.lower()
    if len(message_utilisateur) > 120:
        return True
    return any(mot in msg for mot in _mots_complexes())


_CACHE_MAX = int(os.getenv("MOA_CACHE_MAX", "64"))
_cache_guidance: OrderedDict[str, str] = OrderedDict()


def _hash_contexte(messages: list) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()[:16]


async def _appeler_reference(modele: str, messages: list, config: ConfigMOA,
                              client: httpx.AsyncClient) -> str:
    """Appelle le Gateway pour un seul modèle référence. Retourne le texte brut."""
    system_ref = (
        "Tu es un conseiller analytique dans un processus Mixture of Agents. "
        "Analyse la situation et donne un avis synthétique, factuel, sans exécuter d'actions."
    )
    msgs_ref = [m for m in messages if m.get("role") != "system"]
    payload = {
        "model": modele,
        "messages": [{"role": "system", "content": system_ref}] + msgs_ref,
        "max_tokens": config.max_tokens_ref,
        "temperature": config.temperature_ref,
    }
    gateway_url = os.getenv("GATEWAY_URL", "http://gateway:4000")
    gateway_key = os.getenv("GATEWAY_KEY", "")
    try:
        r = await client.post(
            f"{gateway_url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {gateway_key}"},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("MOA référence %s indisponible : %s", modele, e)
        return f"[référence {modele} indisponible : {e}]"


async def consulter(messages: list, config: ConfigMOA,
                    client: httpx.AsyncClient) -> str:
    """Lance les références en parallèle, synthétise. Retourne la guidance."""
    h = _hash_contexte(messages)
    if h in _cache_guidance:
        return _cache_guidance[h]

    taches = [
        _appeler_reference(m, messages, config, client)
        for m in config.modeles_reference
    ]
    avis = await asyncio.gather(*taches)

    blocs = "\n\n".join(
        f"Référence {i+1} — {config.modeles_reference[i]}:\n{texte}"
        for i, texte in enumerate(avis)
    )
    prompt_agregation = (
        "Voici les avis de plusieurs modèles de référence sur la situation :\n\n"
        f"{blocs}\n\n"
        "Synthétise ces avis en une guidance concise (3-5 phrases max) "
        "à destination du modèle principal. Sois direct et actionnable."
    )
    guidance = await _appeler_reference(
        config.agregateur,
        messages + [{"role": "user", "content": prompt_agregation}],
        config,
        client,
    )
    _cache_guidance[h] = guidance
    _cache_guidance.move_to_end(h)
    if len(_cache_guidance) > _CACHE_MAX:
        _cache_guidance.popitem(last=False)
    return guidance
