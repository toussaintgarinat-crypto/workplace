"""
Router configuration LLM par commune.
Admin only — permet de choisir le provider IA (Anthropic, OpenAI-compatible, Ollama…).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import config as oria_config
from routers.auth import get_current_user
from services.llm_config_service import LLMConfigService, get_llm_config_service

router = APIRouter()

# Presets prêts à l'emploi (affichés dans le frontend)
PRESETS = [
    {"id": "anthropic",  "label": "Anthropic (Claude)",    "provider": "anthropic", "base_url": "", "model": "claude-haiku-4-5-20251001"},
    {"id": "openai",     "label": "OpenAI (GPT-4o)",       "provider": "openai",    "base_url": "https://api.openai.com/v1",       "model": "gpt-4o"},
    {"id": "groq",       "label": "Groq (Llama 3)",        "provider": "openai",    "base_url": "https://api.groq.com/openai/v1",  "model": "llama-3.3-70b-versatile"},
    {"id": "mistral",    "label": "Mistral AI",            "provider": "openai",    "base_url": "https://api.mistral.ai/v1",       "model": "mistral-medium-latest"},
    {"id": "together",   "label": "Together.ai",           "provider": "openai",    "base_url": "https://api.together.xyz/v1",     "model": "meta-llama/Llama-3-70b-chat-hf"},
    {"id": "ollama",     "label": "Ollama (local)",        "provider": "openai",    "base_url": "http://localhost:11434/v1",       "model": "llama3"},
    {"id": "lmstudio",   "label": "LM Studio (local)",     "provider": "openai",    "base_url": "http://localhost:1234/v1",        "model": "local-model"},
    {"id": "custom",     "label": "URL personnalisée",     "provider": "openai",    "base_url": "",                                "model": ""},
]


class LLMConfigIn(BaseModel):
    provider: str          # anthropic | openai
    base_url: Optional[str] = ""
    api_key:  Optional[str] = ""
    model:    str


@router.get("/presets")
def lister_presets():
    return PRESETS


@router.get("/{world_id}")
def lire_config(
    world_id: str,
    svc: LLMConfigService = Depends(get_llm_config_service),
    user=Depends(get_current_user),
):
    if not svc.is_admin(world_id, user["id"]):
        raise HTTPException(403)
    cfg = svc.get_config(world_id)
    if not cfg:
        # Retourner les valeurs par défaut (env vars)
        return {
            "provider": oria_config.LLM_PROVIDER,
            "base_url": oria_config.LLM_BASE_URL,
            "api_key":  "",   # ne jamais exposer la clé env via API
            "model":    oria_config.LLM_MODEL,
            "source":   "env",
        }
    return {
        "provider":   cfg.provider,
        "base_url":   cfg.base_url,
        "api_key":    "***" if cfg.api_key else "",  # masqué
        "model":      cfg.model,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "source":     "db",
    }


@router.put("/{world_id}")
def sauvegarder_config(
    world_id: str,
    body: LLMConfigIn,
    svc: LLMConfigService = Depends(get_llm_config_service),
    user=Depends(get_current_user),
):
    if not svc.is_admin(world_id, user["id"]):
        raise HTTPException(403)
    svc.save_config(
        world_id=world_id, provider=body.provider,
        base_url=body.base_url or "", api_key=body.api_key,
        model=body.model, updated_by=user["id"],
    )
    return {"ok": True}


@router.post("/{world_id}/test")
async def tester_config(
    world_id: str,
    svc: LLMConfigService = Depends(get_llm_config_service),
    user=Depends(get_current_user),
):
    """Envoie un prompt de test et retourne la réponse du LLM configuré."""
    if not svc.is_admin(world_id, user["id"]):
        raise HTTPException(403)
    import httpx
    cfg = svc.resolve_effective_config(world_id)
    provider = cfg["provider"]
    api_key  = cfg["api_key"]
    model    = cfg["model"]
    base_url = cfg["base_url"]
    prompt   = "Réponds en une phrase courte en français : tu es un assistant IA, comment peux-tu aider les utilisateurs ?"

    async with httpx.AsyncClient() as client:
        try:
            if provider == "anthropic":
                if not api_key:
                    return {"response": "[Clé Anthropic manquante]"}
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": model, "max_tokens": 120, "messages": [{"role": "user", "content": prompt}]},
                    timeout=20.0,
                )
                if r.status_code == 200:
                    return {"response": r.json()["content"][0]["text"]}
                return {"response": f"Erreur {r.status_code}: {r.text[:200]}"}
            else:
                if not base_url:
                    return {"response": "[URL du provider non configurée]"}
                headers = {"content-type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                r = await client.post(
                    base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json={"model": model, "max_tokens": 120, "messages": [{"role": "user", "content": prompt}]},
                    timeout=30.0,
                )
                if r.status_code == 200:
                    return {"response": r.json()["choices"][0]["message"]["content"]}
                return {"response": f"Erreur {r.status_code}: {r.text[:200]}"}
        except httpx.ConnectError:
            return {"response": f"Connexion impossible à {base_url or provider}. Serveur démarré ?"}
        except Exception as e:
            return {"response": f"Erreur: {str(e)[:150]}"}


@router.delete("/{world_id}")
def reinitialiser_config(
    world_id: str,
    svc: LLMConfigService = Depends(get_llm_config_service),
    user=Depends(get_current_user),
):
    """Remet la config aux valeurs des variables d'environnement."""
    if not svc.is_admin(world_id, user["id"]):
        raise HTTPException(403)
    svc.delete_config(world_id)
    return {"ok": True, "message": "Config réinitialisée sur les variables d'environnement"}
