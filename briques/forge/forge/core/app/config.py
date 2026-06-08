"""Configuration forge/core — settings via env (pydantic-settings).

Migration strangler forge/core → Python achevée (S136). core est l'unique
backend forge ; le proxy vers le Bun a été retiré. Settings métier consolidés
au fil des sprints S127-S135 (LLM, RAG, SMTP, temps réel, intégrations).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Identité service ────────────────────────────────────────────────
    SERVICE_NAME: str = "forge-core"
    VERSION: str = "1.0.0"  # S136 cutover TERMINÉ : Bun supprimé, core = unique backend forge
    CORE_PY_PORT: int = 8600

    # ── Base de données (partagée avec le Bun, ne bouge pas) ────────────
    # Driver async asyncpg. Même Postgres que forge/core (Drizzle).
    DATABASE_URL: str = "postgresql+asyncpg://forge:forge@localhost:5432/forge"


    # ── CORS ────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000"

    # ── Auth Keycloak (branché quand S127 portera le middleware) ────────
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "forge"
    KEYCLOAK_AUDIENCE: str = ""  # vide = verify_aud désactivé (multi-tenant)

    # ── LLM (S128) — tout passe par la LiteLLM Gateway (OpenAI-compatible) ─
    DEFAULT_LLM_PROVIDER: str = "ollama"
    DEFAULT_LLM_MODEL: str = "llama3.2"
    GATEWAY_BASE_URL: str = "http://gateway:4000"
    GATEWAY_API_KEY: str = "sk-forge"
    OLLAMA_BASE_URL: str = ""  # http://host:11434/api — pour /llm-config/ollama/*
    FALLBACK_LLM_CHAIN: str = ""  # "groq:llama-3.3-70b-versatile,ollama:llama3.2"

    # ── RAG / mémoire (S129) — portage de memory/*.ts ───────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    ML_MODULE_URL: str = "http://localhost:8001"  # embeddings locaux (fastembed) — legacy
    # Workplace S17 : le provider "local" est routé vers la Gateway (modèle all-minilm,
    # 384 dims) au lieu du ml-module torch — un seul moteur d'embeddings pour tout
    # Workplace (même que la brique Mémoire). Surchargeable si besoin.
    LOCAL_EMBED_MODEL: str = "embedding/all-minilm"
    # Clés providers d'embedding API (dispo = clé présente). Embeddings routés gateway.
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    # Brique Mémoire Workplace (port 5600) — enrichissement contexte RAG via le
    # contrat /rappeler + écriture des savoirs via /retenir. Remplace MemPalace.
    # Opt-in : vide = pas d'enrichissement (RAG Qdrant seul). Pas de token : la
    # brique est un adaptateur de confiance interne au réseau Workplace.
    MEMOIRE_URL: str = ""  # ex. http://host.docker.internal:5600
    MEMOIRE_ESPACE: str = ""  # vide = espace solution « Workplace » côté brique

    # ── SMTP (S130) — email de confirmation suppression venture ─────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_SECURE: bool = False
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""

    # ── DevOps & déploiement (S132) — deploy/servers/netbird/cloudflare ─
    # Image du forge-core déployée chez le client (docker-compose généré).
    FORGE_IMAGE: str = "ghcr.io/toussaintgarinat-crypto/forge-core:latest"
    # NetBird (VPN mesh) — proxy d'API avec PAT serveur.
    NETBIRD_API_URL: str = "https://api.netbird.io"
    NETBIRD_TOKEN: str = ""  # vide = endpoints /netbird/* renvoient 503
    # Cloudflare DNS — mode domaine 'cloudflare' (enregistrement A auto).
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""

    # ── Temps réel (S134) — voice (STT/TTS), push (VAPID), realtime ─────
    # STT : Groq (défaut), OpenAI (réutilise OPENAI_API_KEY ci-dessus), Deepgram.
    GROQ_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    # TTS : OpenAI (réutilise OPENAI_API_KEY), ElevenLabs.
    ELEVENLABS_API_KEY: str = ""
    # Web Push VAPID — /push/send (vide ⇒ 503, parité Bun).
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_EMAIL: str = "mailto:admin@localhost"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # extra="ignore" tolère les nombreuses vars d'env du Bun partagées


settings = Settings()
