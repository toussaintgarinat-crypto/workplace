FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir setuptools

# Build-context = RACINE du monorepo (cf. docker-compose.yml) pour embarquer shared/.
# ── Paquet vendored agent_personnel_shared (Redis, FastAPI helpers, HealthBuilder) ──
# Le JWT Keycloak n'en vient PLUS : il vient de shared.workplace_auth (S120).
# Installé AVANT le code service pour bénéficier du cache Docker tant qu'il ne change pas.
COPY briques/forge/shared /opt/agent_personnel_shared
RUN pip install --no-cache-dir /opt/agent_personnel_shared

# Lib partagée du monorepo (S120 : shared.workplace_auth), importable en `shared`.
COPY shared/ /app/shared/

COPY briques/forge/forge/core/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY briques/forge/forge/core/ ./

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8600

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8600/health >/dev/null 2>&1 || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
