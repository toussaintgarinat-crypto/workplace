FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pour le moteur SOUVERAIN Piper, monter/poser un modèle de voix (.onnx) et désigner son
# chemin via PIPER_VOICE (cf. docker-compose.yml). Sans modèle, la brique reste honnête :
# elle bascule sur un fournisseur hébergé configuré, ou rend un placeholder explicite.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5985"]
