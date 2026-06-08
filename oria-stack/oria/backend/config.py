"""
Configuration centralisée Oria (Sprint 100).

Pattern inspiré de mempalace.config.MempalaceConfig.

Toutes les variables d'environnement utilisées par les routers ET les services
sont chargées ici, exposées comme attributs/properties pour faciliter
les tests (monkeypatch) et la documentation.

Usage :
    from config import config
    stripe_key = config.STRIPE_SECRET_KEY
"""

from __future__ import annotations

import os
from typing import Optional


class OriaConfig:
    """Configuration centralisée — toutes les env vars du backend Oria."""

    # ─── Auth / Keycloak ─────────────────────────────────────────────────────
    @property
    def KEYCLOAK_URL(self) -> str:
        return os.getenv("KEYCLOAK_URL", "http://keycloak:8080")

    @property
    def KEYCLOAK_REALM(self) -> str:
        return os.getenv("KEYCLOAK_REALM", "oria")

    @property
    def KEYCLOAK_CLIENT_ID(self) -> str:
        return os.getenv("KEYCLOAK_CLIENT_ID", "oria-app")

    # ─── Forge / Agent par défaut ────────────────────────────────────────────
    @property
    def FORGE_URL(self) -> str:
        return os.getenv("FORGE_URL", "http://localhost:3001")

    @property
    def FORGE_TOKEN(self) -> str:
        return os.getenv("FORGE_TOKEN", "")

    @property
    def DEFAULT_AGENT_PROVIDER(self) -> str:
        return os.getenv("DEFAULT_AGENT_PROVIDER", "openrouter")

    @property
    def DEFAULT_AGENT_MODEL(self) -> str:
        return os.getenv("DEFAULT_AGENT_MODEL", "anthropic/claude-sonnet-4-6")

    # ─── Frontend / URLs publiques ────────────────────────────────────────────
    @property
    def FRONTEND_URL(self) -> str:
        return os.getenv("FRONTEND_URL", "http://localhost:3000")

    # ─── Stripe ───────────────────────────────────────────────────────────────
    @property
    def STRIPE_SECRET_KEY(self) -> Optional[str]:
        return os.getenv("STRIPE_SECRET_KEY")

    @property
    def STRIPE_WEBHOOK_SECRET(self) -> Optional[str]:
        return os.getenv("STRIPE_WEBHOOK_SECRET")

    # ─── LiveKit ──────────────────────────────────────────────────────────────
    @property
    def LIVEKIT_API_KEY(self) -> str:
        return os.getenv("LIVEKIT_API_KEY", "devkey")

    @property
    def LIVEKIT_API_SECRET(self) -> str:
        return os.getenv("LIVEKIT_API_SECRET", "devsecret")

    # ─── Matrix ───────────────────────────────────────────────────────────────
    @property
    def MATRIX_HOMESERVER_URL(self) -> str:
        return os.getenv("MATRIX_HOMESERVER_URL", "http://dendrite:8008")

    @property
    def MATRIX_SERVER_NAME(self) -> str:
        return os.getenv("MATRIX_SERVER_NAME", "oria.local")

    @property
    def MATRIX_AS_TOKEN(self) -> str:
        return os.getenv("MATRIX_AS_TOKEN", "")

    @property
    def MATRIX_HS_TOKEN(self) -> str:
        return os.getenv("MATRIX_HS_TOKEN", "")

    # ─── LLM par défaut (fallback global) ─────────────────────────────────────
    @property
    def LLM_PROVIDER(self) -> str:
        return os.getenv("LLM_PROVIDER", "anthropic")

    @property
    def LLM_BASE_URL(self) -> str:
        return os.getenv("LLM_BASE_URL", "")

    @property
    def LLM_API_KEY(self) -> str:
        return os.getenv("LLM_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))

    @property
    def LLM_MODEL(self) -> str:
        return os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")

    # ─── Calendar service ────────────────────────────────────────────────────
    @property
    def CALENDAR_URL(self) -> str:
        return os.getenv("CALENDAR_URL", "http://calendar:8400")

    @property
    def CALENDAR_SERVICE_TOKEN(self) -> str:
        return os.getenv("CALENDAR_SERVICE_TOKEN", "")

    # ─── Stockage ─────────────────────────────────────────────────────────────
    @property
    def DOCUMENTS_DIR(self) -> str:
        """Répertoire d'upload des documents (jardin/documents)."""
        return os.getenv("DOCUMENTS_DIR", "/tmp/oria_documents")

    @property
    def UPLOAD_DIR(self) -> str:
        """Premier répertoire d'upload disponible (créé à la volée)."""
        candidates = [
            "/app/uploads",
            "/tmp/uploads",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads")),
        ]
        for candidate in candidates:
            try:
                os.makedirs(candidate, exist_ok=True)
                return candidate
            except OSError:
                continue
        return "/tmp/uploads"


# Singleton réutilisable partout
config = OriaConfig()
