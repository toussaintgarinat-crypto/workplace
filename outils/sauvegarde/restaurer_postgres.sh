#!/usr/bin/env bash
# Restaure une base Postgres depuis ses WAL WAL-G, dans un volume Docker neuf.
# Usage : restaurer_postgres.sh <prefixe_s3> <volume_docker_cible> <image_walg>
# Exemple : restaurer_postgres.sh memoire-wal memoire_memoire_pgdata_restaure workplace/memoire-db-walg:0.1.0
set -euo pipefail

PREFIXE="$1"; VOLUME_CIBLE="$2"; IMAGE_WALG="$3"
source "$(dirname "$0")/../../.env"

docker volume create "$VOLUME_CIBLE" >/dev/null

docker run --rm \
  --network proxy_net \
  -e WALG_S3_PREFIX="s3://${SAUVEGARDE_S3_BUCKET}/${PREFIXE}" \
  -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}" \
  -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}" \
  -e AWS_ENDPOINT="${AWS_ENDPOINT}" \
  -e AWS_S3_FORCE_PATH_STYLE=true \
  -e AWS_REGION="${AWS_REGION}" \
  -v "$VOLUME_CIBLE:/var/lib/postgresql/data" \
  --entrypoint wal-g \
  "$IMAGE_WALG" \
  backup-fetch /var/lib/postgresql/data LATEST

echo "Base restaurée (fichiers + WAL de base) dans $VOLUME_CIBLE."
echo "Prochaine étape manuelle : démarrer un conteneur Postgres pointé sur ce volume avec"
echo "restore_command='wal-g wal-fetch %f %p' pour rejouer les WAL jusqu'au dernier connu."
