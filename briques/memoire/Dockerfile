# ── Stage 1 : build du front React (Vite) — projet Memory inclus dans la brique ──
# Le front (memory/frontend) parle à /api/v1 en relatif ; il est buildé en statique
# puis servi par l'adaptateur FastAPI (cf. main.py), qui reverse-proxy /api/v1 vers
# le backend Memory interne. Aucun service web supplémentaire.
FROM node:22-slim AS front
WORKDIR /front
COPY memory/frontend/package*.json ./
RUN npm ci
COPY memory/frontend/ ./
RUN npm run build   # → /front/dist

# ── Stage 2 : l'adaptateur Python ────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Le front buildé est servi depuis /app/ui (UI_DIR), proxy /api/v1 → backend Memory.
COPY --from=front /front/dist /app/ui

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
