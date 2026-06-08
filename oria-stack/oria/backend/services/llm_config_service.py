"""Service LLM Config — accès DB pour llm_config_router (Sprint 100).

Centralise la lecture/écriture des configurations LLM par world,
ainsi que la résolution effective (DB → fallback env vars via OriaConfig).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from config import config as oria_config
from crypto_utils import decrypt_api_key, encrypt_api_key
from database import get_db
from models.llm_config import LLMConfig
from models.world import Member


def _default_base_url(provider: str) -> str:
    return "" if provider == "anthropic" else "https://api.openai.com/v1"


class LLMConfigService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Permissions ──────────────────────────────────────────────────────
    def is_admin(self, world_id: str, user_id: str) -> bool:
        m = self.db.query(Member).filter_by(world_id=world_id, user_id=user_id).first()
        return bool(m and m.role in ("proprietaire", "admin"))

    # ─── Config CRUD ──────────────────────────────────────────────────────
    def get_config(self, world_id: str) -> Optional[LLMConfig]:
        return self.db.query(LLMConfig).filter_by(world_id=world_id).first()

    def save_config(
        self, world_id: str, provider: str, base_url: str,
        api_key: Optional[str], model: str, updated_by: str,
    ) -> LLMConfig:
        cfg = self.get_config(world_id)
        encrypted_key_for_create = encrypt_api_key(api_key) if api_key and api_key != "***" else ""
        if cfg:
            cfg.provider = provider
            cfg.base_url = base_url or ""
            # Si api_key est "***" (masqué), on ne l'écrase pas
            if api_key and api_key != "***":
                cfg.api_key = encrypt_api_key(api_key)
            cfg.model = model
            cfg.updated_by = updated_by
        else:
            cfg = LLMConfig(
                world_id=world_id,
                provider=provider,
                base_url=base_url or "",
                api_key=encrypted_key_for_create,
                model=model,
                updated_by=updated_by,
            )
            self.db.add(cfg)
        self.db.commit()
        return cfg

    def delete_config(self, world_id: str) -> None:
        self.db.query(LLMConfig).filter_by(world_id=world_id).delete()
        self.db.commit()

    # ─── Résolution effective ─────────────────────────────────────────────
    def resolve_effective_config(self, world_id: str) -> dict:
        """Retourne la config LLM effective pour une commune (DB ou env vars)."""
        cfg = self.get_config(world_id)
        if cfg:
            return {
                "provider": cfg.provider,
                "base_url": cfg.base_url or _default_base_url(cfg.provider),
                "api_key": decrypt_api_key(cfg.api_key) or oria_config.LLM_API_KEY,
                "model": cfg.model,
            }
        return {
            "provider": oria_config.LLM_PROVIDER,
            "base_url": oria_config.LLM_BASE_URL or _default_base_url(oria_config.LLM_PROVIDER),
            "api_key": oria_config.LLM_API_KEY,
            "model": oria_config.LLM_MODEL,
        }


def get_llm_config_service(db: Session = Depends(get_db)) -> LLMConfigService:
    return LLMConfigService(db)
