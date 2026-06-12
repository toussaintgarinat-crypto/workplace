FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-télécharge les modèles openWakeWord (~1 Mo chacun) DANS l'image → conteneur
# reproductible, aucune dépendance réseau au démarrage (et /sante honnête).
RUN python -c "import openwakeword.utils as u; u.download_models()"

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5800"]
