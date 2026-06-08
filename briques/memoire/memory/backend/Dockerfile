# Image du backend Memory pour l'exécuter comme brique du stack Workplace.
# Le schéma est auto-créé au démarrage (lifespan → create_all) ; l'extension
# pgvector est activée côté Postgres par un script d'init monté sur la base.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "bcrypt==4.0.1"  # compat passlib 1.7.4 (bcrypt 4.x casse le hash)

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
