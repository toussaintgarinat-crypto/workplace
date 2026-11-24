"""Catalogue vivant des modèles (S244) : la liste proposée dans ⚙ Cerveau vient des
fournisseurs eux-mêmes (`GET …/models`), plus d'identifiant tapé à la main.

Règles de sécurité (le pourquoi) :
- **URLs en dur** : l'appelant ne choisit qu'un `fournisseur` du catalogue serveur. Jamais
  d'URL ni de clé libres (SSRF, cf. `modeles_gateway`) ;
- **la clé ne sort pas** : lue dans le `.env` de la Gateway, envoyée au seul fournisseur
  concerné, jamais renvoyée au front ni journalisée ;
- **le choix reste validé** : un identifiant du menu passe par `modeles_gateway.ajouter`
  (même regex, même test de complétion) ; ici on écarte seulement ceux qui n'en passeraient
  pas la regex.
Cache mémoire ~1 h par fournisseur ; `actualiser=True` le contourne.
"""
from __future__ import annotations

import re
import time

import httpx

import config_assistant
import modeles_gateway

TTL_S = 3600
_TIMEOUT_S = 15.0
_MAX_MODELES = 2000

# Modèles qui ne sont pas du chat (le test de complétion les ferait échouer de toute façon).
_RE_NON_CHAT = re.compile(
    r"embed|whisper|tts|speech|transcri|moderat|rerank|guard|ocr|dall-e|image|imagen|"
    r"video|veo|sora|audio|realtime|diffusion|flux|stable-diffusion|vision-only|"
    r"babbage|davinci|aqa", re.I)


def _bearer(cle: str) -> dict:
    return {"Authorization": f"Bearer {cle}"}


def _ids_data(j) -> list[str]:
    """Forme OpenAI : {"data": [{"id": …}]} (ou liste nue, comme Together)."""
    if not isinstance(j, (dict, list)):
        raise TypeError("réponse inattendue")
    liste = j.get("data", []) if isinstance(j, dict) else j
    return [m["id"] for m in liste if isinstance(m, dict) and isinstance(m.get("id"), str)]


def _openrouter(j) -> list[str]:
    sortie = []
    for m in j.get("data", []):
        mods = (m.get("architecture") or {}).get("output_modalities") or ["text"]
        if mods == ["text"] and isinstance(m.get("id"), str):
            sortie.append(m["id"])
    return sortie


def _mistral(j) -> list[str]:
    return [m["id"] for m in j.get("data", [])
            if isinstance(m.get("id"), str)
            and (m.get("capabilities") or {}).get("completion_chat", True)]


def _gemini(j) -> list[str]:
    return [m["name"].removeprefix("models/") for m in j.get("models", [])
            if isinstance(m.get("name"), str)
            and "generateContent" in (m.get("supportedGenerationMethods") or [])]


def _anthropic(j) -> list[str]:
    return _ids_data(j)


def _together(j) -> list[str]:
    liste = j if isinstance(j, list) else j.get("data", [])
    return [m["id"] for m in liste
            if isinstance(m.get("id"), str) and m.get("type", "chat") in ("chat", "language")]


def _cohere(j) -> list[str]:
    return [m["name"] for m in j.get("models", []) if isinstance(m.get("name"), str)
            and "chat" in (m.get("endpoints") or ["chat"])]


# id fournisseur → (URL fixe, fabrique d'en-têtes(clé), extracteur, clé requise)
SOURCES: dict[str, dict] = {
    "openrouter": {"url": "https://openrouter.ai/api/v1/models", "entetes": lambda k: {},
                   "extraire": _openrouter, "cle_requise": False},
    "anthropic": {"url": "https://api.anthropic.com/v1/models?limit=1000",
                  "entetes": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"},
                  "extraire": _anthropic, "cle_requise": True},
    "openai": {"url": "https://api.openai.com/v1/models", "entetes": _bearer,
               "extraire": _ids_data, "cle_requise": True},
    "groq": {"url": "https://api.groq.com/openai/v1/models", "entetes": _bearer,
             "extraire": _ids_data, "cle_requise": True},
    "deepseek": {"url": "https://api.deepseek.com/models", "entetes": _bearer,
                 "extraire": _ids_data, "cle_requise": True},
    "mistral": {"url": "https://api.mistral.ai/v1/models", "entetes": _bearer,
                "extraire": _mistral, "cle_requise": True},
    "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
               "entetes": lambda k: {"x-goog-api-key": k},
               "extraire": _gemini, "cle_requise": True},
    "zai": {"url": "https://api.z.ai/api/paas/v4/models", "entetes": _bearer,
            "extraire": _ids_data, "cle_requise": True},
    "together": {"url": "https://api.together.xyz/v1/models", "entetes": _bearer,
                 "extraire": _together, "cle_requise": True},
    "fireworks": {"url": "https://api.fireworks.ai/inference/v1/models?pageSize=200",
                  "entetes": _bearer, "extraire": _ids_data, "cle_requise": True},
    "xai": {"url": "https://api.x.ai/v1/models", "entetes": _bearer,
            "extraire": _ids_data, "cle_requise": True},
    "cohere": {"url": "https://api.cohere.com/v1/models?endpoint=chat", "entetes": _bearer,
               "extraire": _cohere, "cle_requise": True},
}

_cache: dict[str, tuple[float, list[str]]] = {}


def _nettoyer(ids: list[str]) -> list[str]:
    """Garde les identifiants de chat que `valider_identifiant` accepterait, triés, uniques."""
    sortie = set()
    for i in ids:
        if _RE_NON_CHAT.search(i):
            continue
        try:
            sortie.add(modeles_gateway.valider_identifiant(i))
        except modeles_gateway.ValeurInvalide:
            continue
    return sorted(sortie)[:_MAX_MODELES]


def _cle(fournisseur: str) -> str:
    env = next((f["env"] for f in config_assistant.FOURNISSEURS_CLES if f["id"] == fournisseur), "")
    val = config_assistant._lire_cle_env(env) if env else ""
    return val if config_assistant._cle_definie(val) else ""


async def lister(fournisseur: str, actualiser: bool = False) -> dict:
    """{fournisseur, etat: ok|cle_absente|erreur, modeles: [id…], detail, age_s}."""
    src = SOURCES.get(fournisseur)
    if src is None or fournisseur not in modeles_gateway._catalogue():
        raise modeles_gateway.ValeurInvalide(f"Fournisseur inconnu : {fournisseur!r}.")
    cle = _cle(fournisseur)
    if src["cle_requise"] and not cle:
        return {"fournisseur": fournisseur, "etat": "cle_absente", "modeles": [],
                "detail": "Clé absente : pose-la dans ⚙ Cerveau pour voir ses modèles.",
                "age_s": 0}
    maintenant = time.monotonic()
    en_cache = _cache.get(fournisseur)
    if en_cache and not actualiser and maintenant - en_cache[0] < TTL_S:
        return {"fournisseur": fournisseur, "etat": "ok", "modeles": en_cache[1],
                "detail": "", "age_s": int(maintenant - en_cache[0])}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=False) as c:
            r = await c.get(src["url"], headers=src["entetes"](cle))
            r.raise_for_status()
            ids = _nettoyer(src["extraire"](r.json()))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
        # Jamais `str(e)` : un message httpx peut citer l'URL, et on ne sait pas ce qu'un
        # fournisseur renvoie. Le type et le statut suffisent.
        statut = getattr(getattr(e, "response", None), "status_code", None)
        # Liste périmée plutôt que menu vide si on en a une.
        if en_cache:
            return {"fournisseur": fournisseur, "etat": "ok", "modeles": en_cache[1],
                    "detail": f"Actualisation impossible ({type(e).__name__}) : liste en cache.",
                    "age_s": int(maintenant - en_cache[0])}
        return {"fournisseur": fournisseur, "etat": "erreur", "modeles": [],
                "detail": f"Catalogue indisponible ({type(e).__name__}"
                          + (f", HTTP {statut}" if statut else "") + ").", "age_s": 0}
    _cache[fournisseur] = (maintenant, ids)
    return {"fournisseur": fournisseur, "etat": "ok", "modeles": ids, "detail": "", "age_s": 0}
