FROM python:3.12-slim

WORKDIR /app

# Aucune lib native ClamAV ici : ce service parle le protocole clamd (INSTREAM) au
# conteneur sidecar `audit-fichiers-clamav` du docker-compose.yml — clamd lui-même
# n'est jamais installé dans CETTE image (cf. scanners/clamav.py amont, même séparation).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6170"]
