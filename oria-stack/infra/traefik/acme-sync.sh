#!/usr/bin/env bash
# infra/traefik/acme-sync.sh
#
# Exporte acme.json depuis le volume Traefik HP et le synchronise vers Node 2.
# Permet au Traefik N2 d'utiliser les certs Let's Encrypt existants sans refaire
# une validation (évite les rate limits LE).
#
# Usage : bash infra/traefik/acme-sync.sh
#
# Variables requises :
#   NODE2_NETBIRD_IP   IP NetBird du Node 2
#   NODE2_SSH_USER     Utilisateur SSH Node 2 (défaut: root)
#
# Variables optionnelles :
#   TRAEFIK_VOLUME     Nom du volume Docker Traefik HP (défaut: traefik_letsencrypt)
#   TRAEFIK_N2_VOLUME  Nom du volume Docker Traefik N2 (défaut: traefik_letsencrypt-n2)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_ENV="${SCRIPT_DIR}/../../.env"
[[ -f "$ROOT_ENV" ]] && set -a && source "$ROOT_ENV" && set +a

: "${NODE2_NETBIRD_IP:?NODE2_NETBIRD_IP requis}"
NODE2_SSH_USER="${NODE2_SSH_USER:-root}"
TRAEFIK_VOLUME="${TRAEFIK_VOLUME:-traefik_letsencrypt}"
TRAEFIK_N2_VOLUME="${TRAEFIK_N2_VOLUME:-traefik_letsencrypt-n2}"
TMP_ACME="/tmp/acme-hp-$(date +%Y%m%d%H%M%S).json"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Étape 1 : extraire acme.json depuis le volume HP
log "Extraction acme.json depuis volume ${TRAEFIK_VOLUME}..."
docker run --rm \
  -v "${TRAEFIK_VOLUME}:/data:ro" \
  alpine sh -c 'cat /data/acme.json' > "${TMP_ACME}"

if [[ ! -s "${TMP_ACME}" ]]; then
  echo "Erreur : acme.json vide ou introuvable dans ${TRAEFIK_VOLUME}" >&2
  exit 1
fi
chmod 600 "${TMP_ACME}"
log "  ✓ acme.json extrait ($(wc -c < "${TMP_ACME}") octets)"

# Étape 2 : copier vers Node 2
log "Copie vers ${NODE2_SSH_USER}@${NODE2_NETBIRD_IP}:/tmp/acme-from-hp.json..."
scp -q "${TMP_ACME}" "${NODE2_SSH_USER}@${NODE2_NETBIRD_IP}:/tmp/acme-from-hp.json"
log "  ✓ Copie OK"

# Étape 3 : injecter dans le volume N2
log "Injection dans le volume ${TRAEFIK_N2_VOLUME} sur Node 2..."
ssh "${NODE2_SSH_USER}@${NODE2_NETBIRD_IP}" bash -s << EOF
docker run --rm \
  -v "${TRAEFIK_N2_VOLUME}:/data" \
  -v /tmp/acme-from-hp.json:/src/acme.json:ro \
  alpine sh -c 'cp /src/acme.json /data/acme.json && chmod 600 /data/acme.json'
rm -f /tmp/acme-from-hp.json
echo "  ✓ acme.json injecté dans ${TRAEFIK_N2_VOLUME}"
EOF

# Nettoyage local
rm -f "${TMP_ACME}"

log "acme-sync terminé — Traefik N2 peut démarrer avec les certs HP existants."
log "Redémarrer Traefik N2 pour prendre en compte : docker compose -f infra/traefik/compose-node2.yml restart traefik"
