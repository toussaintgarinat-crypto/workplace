# Image de l'adaptateur Forge (contrat Workplace en français). Volontairement
# minimale : elle ne copie QUE l'adaptateur (main.py + requirements), pas le core
# vendorisé sous ./forge — celui-ci a son propre build (forge/core/Dockerfile).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
