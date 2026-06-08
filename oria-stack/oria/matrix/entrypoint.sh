#!/bin/sh
set -e

export MATRIX_SERVER_NAME="${MATRIX_SERVER_NAME:-oria.local}"
export POSTGRES_USER="${POSTGRES_USER:-oria}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-oria_secret}"
export MATRIX_REGISTRATION_DISABLED="${MATRIX_REGISTRATION_DISABLED:-true}"

envsubst '${MATRIX_SERVER_NAME},${POSTGRES_USER},${POSTGRES_PASSWORD},${MATRIX_REGISTRATION_SHARED_SECRET},${MATRIX_REGISTRATION_DISABLED}' \
  < /etc/dendrite/dendrite.yaml.tpl > /etc/dendrite/dendrite.yaml

envsubst '${MATRIX_AS_TOKEN},${MATRIX_HS_TOKEN},${MATRIX_SERVER_NAME}' \
  < /etc/dendrite/appservice.yaml.tpl > /etc/dendrite/appservice.yaml

if [ ! -f /var/dendrite/keys/matrix_key.pem ]; then
  mkdir -p /var/dendrite/keys
  generate-keys --private-key /var/dendrite/keys/matrix_key.pem
fi

DENDRITE_BIN=$(which dendrite-monolith 2>/dev/null || which dendrite 2>/dev/null || echo "/usr/bin/dendrite-monolith")
exec "$DENDRITE_BIN" --config /etc/dendrite/dendrite.yaml
