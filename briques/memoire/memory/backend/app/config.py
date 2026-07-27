from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://memory:memory@localhost:5432/memory"
    llm_provider: str = "openrouter"
    llm_api_key: Optional[str] = None
    llm_model: str = "anthropic/claude-3.5-sonnet"
    llm_base_url: Optional[str] = None
    embedding_model: str = "text-embedding-3-small"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    mcp_server_port: int = 8100
    tier_hot_days: int = 30
    tier_archive_days: int = 90
    tier_cold_archive_days: int = 365
    gardien_default_mode: str = "propose"
    gardien_default_interval_minutes: int = 60

    # extra="ignore" : `env_file` fait entrer TOUTES les clés du .env dans la validation, et
    # ce .env est partagé (docker-compose, Postgres, autres briques). Avec le défaut de
    # pydantic-settings (extra="forbid"), une variable qui ne concerne même pas ce service —
    # MEMOIRE_DB_PASSWORD, lue par le compose — faisait échouer `Settings()` À L'IMPORT, donc
    # planter le backend au démarrage. Même arbitrage que briques/forge (config.py:101).
    # Contrepartie assumée : une faute de frappe dans un nom de variable passe désormais
    # inaperçue au lieu d'être signalée.
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
