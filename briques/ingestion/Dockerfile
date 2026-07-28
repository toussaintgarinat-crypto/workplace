FROM python:3.11-slim

# Tesseract pour l'OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

VOLUME ["/data"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5200"]
