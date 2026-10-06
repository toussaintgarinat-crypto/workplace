#!/usr/bin/env bash
# S241 — exécute une commande de forge/core contre un Postgres 16.14 et un Qdrant v1.12.4 NEUFS.
#
# Les tests d'intégration de la recherche exigent une vraie base (plein texte, trigrammes,
# colonnes générées) et un vrai Qdrant (filtres de payload) : un mock aurait caché exactement
# la fuite que S241 corrige. Mêmes images que la production (briques/forge/docker-compose.yml),
# Python du Dockerfile (3.12). Tout est détruit à la sortie.
#
# Usage (depuis briques/forge/forge/core) :
#   scripts/en_docker.sh python -m pytest -p no:cacheprovider -q [args pytest…]
#   scripts/en_docker.sh python -m scripts.mesure_recherche_s241
# Transmises au conteneur si définies : GATEWAY_BASE_URL GATEWAY_API_KEY LOCAL_EMBED_MODEL.
set -euo pipefail

[ $# -gt 0 ] || { echo "usage : $0 <commande…>" >&2; exit 2; }

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RACINE="$(cd "$ICI/../../../.." && pwd)"
SUFFIXE="$$"
RESEAU="forge-essai-$SUFFIXE"
BASE="forge-essai-db-$SUFFIXE"
QDRANT="forge-essai-qdrant-$SUFFIXE"

nettoyer() {
  docker rm -f "$BASE" "$QDRANT" >/dev/null 2>&1 || true
  docker network rm "$RESEAU" >/dev/null 2>&1 || true
}
trap nettoyer EXIT

docker network create "$RESEAU" >/dev/null
docker run -d --name "$BASE" --network "$RESEAU" \
  -e POSTGRES_USER=forge -e POSTGRES_PASSWORD=forge -e POSTGRES_DB=forge_test \
  postgres:16.14 >/dev/null
docker run -d --name "$QDRANT" --network "$RESEAU" qdrant/qdrant:v1.12.4 >/dev/null

pret=0
for _ in $(seq 1 60); do
  # Par TCP : pendant l'initialisation, l'image démarre un serveur provisoire sur la socket Unix.
  if docker exec "$BASE" pg_isready -h 127.0.0.1 -U forge -d forge_test >/dev/null 2>&1; then pret=1; break; fi
  sleep 1
done
[ "$pret" = 1 ] || { echo "✗ Postgres de test jamais prêt" >&2; exit 1; }

transmises=()
for v in GATEWAY_BASE_URL GATEWAY_API_KEY LOCAL_EMBED_MODEL; do
  if [ -n "${!v:-}" ]; then transmises+=(-e "$v=${!v}"); fi
done

docker run --rm --network "$RESEAU" -v "$RACINE":/monorepo:ro \
  -w /monorepo/briques/forge/forge/core \
  --add-host host.docker.internal:host-gateway \
  -e DATABASE_URL="postgresql+asyncpg://forge:forge@$BASE:5432/forge_test" \
  -e QDRANT_URL="http://$QDRANT:6333" \
  -e FORGE_TEST_INTEGRATION=1 -e FORGE_RECONCILIATION=0 \
  -e PYTHONPATH="/monorepo:/monorepo/briques/forge/shared" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e VAULT_SECRET=test-secret-0123456789 -e GATEWAY_KEY=test \
  ${transmises[@]+"${transmises[@]}"} \
  python:3.12-slim sh -c '
    pip install -q --no-cache-dir --root-user-action=ignore -r requirements.txt -r requirements-dev.txt >/dev/null &&
    python -c "
import os, time, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen(os.environ[\"QDRANT_URL\"] + \"/readyz\", timeout=2)
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit(\"✗ Qdrant de test jamais prêt\")
" &&
    exec "$@"' _ "$@"
