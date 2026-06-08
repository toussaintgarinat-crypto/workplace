FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir setuptools

# ── Shared utilities (Redis, Keycloak, FastAPI helpers, HealthBuilder) ──
# Build context = repo root (cf. docker-compose.yml). Installé AVANT le code
# service pour bénéficier du cache Docker tant que shared/ ne change pas.
# ⚠️ shared/ est COPIÉ (pas monté) → `docker compose build` requis après modif.
COPY shared /shared
RUN pip install --no-cache-dir /shared

COPY forge/core/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY forge/core/ ./

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8600

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8600/health >/dev/null 2>&1 || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
