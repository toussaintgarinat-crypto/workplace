FROM python:3.12-slim

WORKDIR /app

# Lib partagée du monorepo (S120 : shared.workplace_auth), importable en `shared` — même
# motif que briques/agenda/backend/Dockerfile.
COPY shared/ /app/shared/

COPY core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ .

EXPOSE 5000

# --proxy-headers : derrière Caddy (accès distant mesh, S128) le Cœur sert en HTTP
# interne ; on fait confiance à X-Forwarded-Proto/-For pour reconstruire les URLs
# d'iframe en HTTPS. --forwarded-allow-ips=* car l'IP du proxy (réseau Docker/mesh)
# n'est pas fixe ; réseau de confiance (LAN + mesh privés).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--proxy-headers", "--forwarded-allow-ips", "*"]
