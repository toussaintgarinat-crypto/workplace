#!/usr/bin/env bash
# S238 — exécute une commande du backend Memory contre un Postgres+pgvector NEUF, dans Docker.
#
# Les tests du backend exigent une vraie base (pgvector, plein texte, trigrammes) : on monte
# un réseau jetable et la même image de base que la production (pgvector/pgvector:0.8.2-pg16),
# puis la commande tourne sous le Python du Dockerfile (3.12). Tout est détruit à la sortie.
#
# Usage (depuis briques/memoire/memory/backend) :
#   scripts/en_docker.sh python -m pytest -q [args pytest…]
#   scripts/en_docker.sh python scripts/mesure_recherche.py
# Transmises au conteneur si définies : LLM_PROVIDER LLM_BASE_URL LLM_API_KEY EMBEDDING_MODEL.
set -euo pipefail

[ $# -gt 0 ] || { echo "usage : $0 <commande…>" >&2; exit 2; }

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUFFIXE="$$"
RESEAU="memoire-essai-$SUFFIXE"
BASE="memoire-essai-db-$SUFFIXE"

nettoyer() {
  docker rm -f "$BASE" >/dev/null 2>&1 || true
  docker network rm "$RESEAU" >/dev/null 2>&1 || true
}
trap nettoyer EXIT

docker network create "$RESEAU" >/dev/null
docker run -d --name "$BASE" --network "$RESEAU" \
  -e POSTGRES_USER=memory -e POSTGRES_PASSWORD=memory -e POSTGRES_DB=memory_test \
  pgvector/pgvector:0.8.2-pg16 >/dev/null

pret=0
for _ in $(seq 1 60); do
  # Par TCP : pendant l'initialisation, l'image démarre un serveur provisoire qui n'écoute
  # que sur la socket Unix, puis le redémarre — le tester par la socket donnerait un faux prêt.
  if docker exec "$BASE" pg_isready -h 127.0.0.1 -U memory -d memory_test >/dev/null 2>&1; then pret=1; break; fi
  sleep 1
done
[ "$pret" = 1 ] || { echo "✗ Postgres de test jamais prêt" >&2; exit 1; }

transmises=()
for v in LLM_PROVIDER LLM_BASE_URL LLM_API_KEY EMBEDDING_MODEL; do
  if [ -n "${!v:-}" ]; then transmises+=(-e "$v=${!v}"); fi
done

docker run --rm --network "$RESEAU" -v "$ICI":/src:ro -w /src \
  --add-host host.docker.internal:host-gateway \
  -e TEST_DATABASE_URL="postgresql+asyncpg://memory:memory@$BASE:5432/memory_test" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  ${transmises[@]+"${transmises[@]}"} \
  python:3.12-slim sh -c '
    pip install -q --no-cache-dir --root-user-action=ignore -r requirements.txt "bcrypt==4.0.1" >/dev/null &&
    exec "$@"' _ "$@"
