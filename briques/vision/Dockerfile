FROM python:3.12-slim

WORKDIR /app

# Binaire Tesseract + langues FR/EN (moteur OCR souverain pour les images scannées).
# Retirer ce bloc pour une image plus mince (cascade hébergée Mistral/Google seule).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-local.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-local.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5960"]
