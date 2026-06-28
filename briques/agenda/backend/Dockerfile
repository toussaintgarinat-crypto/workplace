FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir setuptools

# Build-context = RACINE du monorepo (cf. docker-compose.yml) pour embarquer shared/.
# Paquet vendored agent_personnel_shared (Redis, helpers FastAPI, S2S, jobs…) — le JWT
# Keycloak n'en fait PLUS partie côté usage : il vient de shared.workplace_auth (S120).
COPY briques/agenda/shared /opt/agent_personnel_shared
RUN pip install --no-cache-dir -e /opt/agent_personnel_shared

# Lib partagée du monorepo (S120 : shared.workplace_auth), importable en `shared`.
COPY shared/ /app/shared/

COPY briques/agenda/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY briques/agenda/backend/ ./

RUN mkdir -p /data/calendar/attachments && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8400

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8400/health >/dev/null 2>&1 || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400"]
