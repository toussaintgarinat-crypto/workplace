FROM python:3.12-slim

WORKDIR /app

# WeasyPrint : rendu PDF déterministe (Markdown→HTML→PDF). Ces libs natives sont
# nécessaires au RUNTIME (l'appel HTML(...).write_pdf()), pas au moment du `pip install` —
# c'est pourquoi les tests offline (Task 3) mockent le point d'appel WeasyPrint plutôt que
# d'exiger ces libs sur la machine qui lance pytest en dehors de Docker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
    libffi8 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6150"]
