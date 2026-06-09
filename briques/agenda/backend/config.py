import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    DB_PATH: str = "/data/calendar.db" if os.path.isdir("/data") else "./calendar.db"
    REDIS_URL: str = ""
    CORS_ORIGINS: str = "http://localhost:8300,http://localhost:3000"
    AUTH_ENABLED: bool = False
    KEYCLOAK_URL: str = "http://localhost:8080"
    # URL Keycloak vue du navigateur (page d'acceptation d'invitation). Vide ⇒
    # on retombe sur KEYCLOAK_URL. En déploiement : https://auth.${DOMAIN}.
    KEYCLOAK_PUBLIC_URL: str = ""
    KEYCLOAK_REALM: str = "forge"
    KEYCLOAK_CLIENT_ID: str = "calendar-app"
    KEYCLOAK_AUDIENCE: str = ""

    # Token partagé pour les appels S2S inter-services (assistant → calendar, etc.)
    CALENDAR_SERVICE_TOKEN: str = ""

    # Stockage pièces jointes (local filesystem)
    ATTACHMENTS_DIR: str = "/data/calendar/attachments"

    # ── Coffre de tokens chiffrés (rapatrié de l'assistant) ────────────────────
    # Secret qui dérive la clé AES-GCM des tokens OAuth stockés par utilisateur.
    # Obligatoire dès qu'on stocke un token (le coffre lève sinon). En prod : au
    # coffre chiffré, jamais en clair dans l'image.
    VAULT_SECRET: str = ""

    # ── Pont Google Agenda (sync consentie, pull one-way) ──────────────────────
    # Identifiants OAuth2 d'un projet Google Cloud (scope calendar.readonly).
    # Vides ⇒ le pont est désactivé (les endpoints /google/* renvoient 503).
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # URI de redirection enregistrée côté Google Cloud (doit matcher à l'octet près).
    GOOGLE_REDIRECT_URI: str = "http://localhost:8400/google/callback"
    GOOGLE_SCOPE: str = "https://www.googleapis.com/auth/calendar.readonly"

    class Config:
        env_file = ".env"


settings = Settings()
