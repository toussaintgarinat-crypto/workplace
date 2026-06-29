# Build-context = RACINE du monorepo (cf. docker-compose.yml) pour embarquer shared/.
# Les chemins COPY sont donc relatifs à la racine.
FROM python:3.11-slim

WORKDIR /app

COPY briques/audit/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Lib partagée (S118) + code de la brique.
COPY shared/ /app/shared/
COPY briques/audit/ /app/

RUN mkdir -p /data

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5300"]
