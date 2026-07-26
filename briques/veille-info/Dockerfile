FROM python:3.12-slim

WORKDIR /app

# ffmpeg/ffprobe : concaténation de l'audio global (Task 5, motif déjà en prod dans
# briques/voix — même dépendance, cf. briques/voix/Dockerfile).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6120"]
