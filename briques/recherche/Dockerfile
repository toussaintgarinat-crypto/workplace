FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Playwright optionnel (pages JS/SPA) — activé uniquement si --build-arg PLAYWRIGHT=1.
# Ajoute ~400 Mo (Chromium + dépendances système) : n'utiliser qu'en cas de besoin.
ARG PLAYWRIGHT=0
RUN if [ "$PLAYWRIGHT" = "1" ]; then \
      pip install --no-cache-dir playwright && \
      playwright install chromium --with-deps; \
    fi

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6040"]
