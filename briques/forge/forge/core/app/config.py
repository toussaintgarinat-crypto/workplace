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

    # S230 — identité du compte de service côté core : permet à `get_venture`/
    # `update_venture` de reconnaître un appel de service (ex. le mappeur best-effort
    # de la brique `connecteurs`, qui tourne sans JWT utilisateur à propager) plutôt que
    # de le traiter comme un utilisateur normal soumis à `owner_id`. Même valeur par
    # défaut que `FORGE_SERVICE_CLIENT_ID` côté adaptateur (briques/forge/main.py) —
    # à aligner explicitement si les deux services ont des .env séparés.
    FORGE_SERVICE_CLIENT_ID: str = "forge-service"

    # ── LLM (S128) — tout passe par la LiteLLM Gateway (OpenAI-compatible) ─
    DEFAULT_LLM_PROVIDER: str = "opencode"
    DEFAULT_LLM_MODEL: str = "go/deepseek-v4-flash"
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

    # S227 — socle Entité Entreprise unifiée : ponts vers geo/audit/ingestion
    # pour GET /ventures/{id}/dossier. Vide = section correspondante marquée
    # "indisponible" dans la réponse agrégée (repli honnête, jamais de 500).
    GEO_URL: str = ""  # ex. http://host.docker.internal:6110
    GEO_KEY: str = ""  # doit figurer dans API_KEYS de la brique geo
    AUDIT_URL: str = ""  # ex. http://host.docker.internal:5300
    INGESTION_URL: str = ""  # ex. http://host.docker.internal:5200
    INGESTION_KEY: str = ""  # doit figurer dans INGESTION_API_KEYS/API_KEYS de ingestion

    # ── SMTP (S130 ; étendu S22 — emails transactionnels & relances) ────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_SECURE: bool = False  # True ⇒ SMTPS (SSL implicite, port 465)
    # STARTTLS sur connexion claire (587). False pour un relais interne/dev sans TLS.
    SMTP_STARTTLS: bool = True
    SMTP_USER: str = ""
    # Mot de passe : repli env si pas de mot de passe chiffré en base (provider `smtp`).
    # Préférer le coffre (`resolve_smtp_password`) — ne jamais laisser en clair en prod.
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""

    # ── Paiement Stripe réel (S21) — checkout + webhook signé ───────────
    # Clé secrète : repli env si pas de clé chiffrée en base (provider `stripe`).
    # Vide ⇒ checkout en mode `mock` (dégradation honnête, parité historique).
    STRIPE_SECRET_KEY: str = ""
    # Secret de signature des webhooks (whsec_…). Vide ⇒ webhook refuse en
    # présence d'une vraie clé (jamais d'événement non vérifié accepté en prod).
    STRIPE_WEBHOOK_SECRET: str = ""
    # Redirections post-paiement (Checkout hébergé Stripe).
    STRIPE_SUCCESS_URL: str = "http://localhost:3000/paiement/succes"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/paiement/annule"

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
