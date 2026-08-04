#!/usr/bin/env bash
# Restaure une base SQLite depuis sa réplique Litestream, dans un volume Docker neuf.
# Usage : restaurer_sqlite.sh <brique> <chemin_db_dans_le_volume> <volume_docker_cible>
# Exemple : restaurer_sqlite.sh donnees /data/donnees.db donnees_donnees_data
set -euo pipefail

BRIQUE="$1"; CHEMIN_DB="$2"; VOLUME_CIBLE="$3"

# La commande "litestream restore" prend une REPLICA_URL déjà entièrement qualifiée
# (identifiants inclus) en argument positionnel — cette URL est construite ICI, par CE
# script, AVANT même de lancer `docker run`. Elle a donc besoin des variables
# SAUVEGARDE_S3_* dans l'environnement de CE shell, pas seulement dans le conteneur :
# passer un `--env-file` à `docker run` (comme envisagé initialement) ne les rendrait
# visibles qu'À L'INTÉRIEUR du conteneur, une fois trop tard pour l'expansion `${...}`
# ci-dessous — vérifié en le testant, ce n'est pas juste une supposition.
source "$(dirname "$0")/../../.env"

docker volume create "$VOLUME_CIBLE" >/dev/null

# Vérifié en le testant (dry-run) : quand `litestream restore` reçoit une REPLICA_URL
# nue (pas un fichier -config), les paramètres `access-key-id`/`secret-access-key` de la
# query string — pourtant des clés valides du fichier de config — sont IGNORÉS pour
# l'authentification. Les identifiants doivent passer par la chaîne standard AWS
# (variables d'environnement AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY dans le conteneur),
# faute de quoi litestream tente l'IMDS EC2 et échoue avec "no EC2 IMDS role found".
# `endpoint`, `force-path-style` et `region` restent, eux, lus depuis la query string.
docker run --rm \
  --network proxy_net \
  -e AWS_ACCESS_KEY_ID="${SAUVEGARDE_S3_ACCESS_KEY}" \
  -e AWS_SECRET_ACCESS_KEY="${SAUVEGARDE_S3_SECRET_KEY}" \
  -v "$VOLUME_CIBLE:/data" \
  litestream/litestream:0.5.15 \
  restore -o "$CHEMIN_DB" \
  "s3://${SAUVEGARDE_S3_BUCKET}/${BRIQUE}?endpoint=${SAUVEGARDE_S3_ENDPOINT}&force-path-style=true&region=${SAUVEGARDE_S3_REGION}"

echo "Restauré dans le volume $VOLUME_CIBLE : $CHEMIN_DB"
