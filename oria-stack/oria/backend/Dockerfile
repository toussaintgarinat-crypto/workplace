FROM python:3.12-slim
WORKDIR /app
RUN pip install --upgrade pip setuptools wheel

# Build context = repo root (cf. oria/docker-compose.yml).
# ── Shared utilities (Redis, Keycloak, FastAPI helpers) ──────────────
COPY shared /shared
RUN pip install --no-cache-dir -e /shared

COPY oria/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY oria/backend/ ./
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
