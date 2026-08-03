FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --proxy-headers : derrière Caddy (mesh_caddy, network_mode: host → reverse_proxy
# localhost:6220) le conteneur ne voit pas l'IP réelle du client sans faire confiance à
# X-Forwarded-For — même motif que core/Dockerfile. --forwarded-allow-ips=* car le seul
# appelant légitime est mesh_caddy sur le même hôte (port désormais borné à 127.0.0.1,
# voir docker-compose.yml).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6220", "--proxy-headers", "--forwarded-allow-ips", "*"]
