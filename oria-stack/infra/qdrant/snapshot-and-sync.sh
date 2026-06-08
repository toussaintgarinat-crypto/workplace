#!/usr/bin/env bash
# snapshot-and-sync.sh — Qdrant snapshot horaire + rsync vers Node 2 (stub)
#
# Usage:
#   ./snapshot-and-sync.sh [collection]
#
# Env vars (override via .env or shell):
#   QDRANT_URL        http://localhost:6334  (port exposé Docker)
#   QDRANT_SNAPSHOTS  /tmp/qdrant-snapshots  (répertoire local)
#   NODE2_IP          (vide = rsync désactivé)
#   NODE2_SSH_KEY     ~/.ssh/id_ed25519
#   NODE2_SSH_USER    ubuntu
#   NODE2_SNAPSHOT_DIR /var/lib/qdrant-snapshots
#   RETENTION_HOURS   24   (snapshots conservés localement)

set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6334}"
QDRANT_SNAPSHOTS="${QDRANT_SNAPSHOTS:-/tmp/qdrant-snapshots}"
NODE2_IP="${NODE2_IP:-}"
NODE2_SSH_KEY="${NODE2_SSH_KEY:-$HOME/.ssh/id_ed25519}"
NODE2_SSH_USER="${NODE2_SSH_USER:-ubuntu}"
NODE2_SNAPSHOT_DIR="${NODE2_SNAPSHOT_DIR:-/var/lib/qdrant-snapshots}"
RETENTION_HOURS="${RETENTION_HOURS:-24}"
COLLECTION="${1:-}"

mkdir -p "$QDRANT_SNAPSHOTS"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# ── Lister les collections si aucune n'est spécifiée ──────────────
if [[ -z "$COLLECTION" ]]; then
  COLLECTIONS=$(curl -sf "$QDRANT_URL/collections" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('\n'.join(c['name'] for c in d['result']['collections']))" \
    2>/dev/null || true)
  if [[ -z "$COLLECTIONS" ]]; then
    log "ERROR: impossible de lister les collections Qdrant à $QDRANT_URL"
    exit 1
  fi
else
  COLLECTIONS="$COLLECTION"
fi

TIMESTAMP=$(date -u '+%Y%m%d-%H%M%S')
ERRORS=0

for COL in $COLLECTIONS; do
  log "Snapshot collection: $COL"

  SNAP_RESP=$(curl -sf -X POST "$QDRANT_URL/collections/$COL/snapshots" 2>/dev/null || true)
  if [[ -z "$SNAP_RESP" ]]; then
    log "ERROR: échec snapshot $COL"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  SNAP_NAME=$(echo "$SNAP_RESP" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['name'])" 2>/dev/null || true)
  if [[ -z "$SNAP_NAME" ]]; then
    log "ERROR: nom snapshot vide pour $COL"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  # Télécharger le snapshot
  DEST="$QDRANT_SNAPSHOTS/${COL}_${TIMESTAMP}.snapshot"
  curl -sf "$QDRANT_URL/collections/$COL/snapshots/$SNAP_NAME" -o "$DEST"
  SIZE=$(du -sh "$DEST" | cut -f1)
  log "OK $COL → $DEST ($SIZE)"

  # Supprimer le snapshot serveur (libérer espace Qdrant)
  curl -sf -X DELETE "$QDRANT_URL/collections/$COL/snapshots/$SNAP_NAME" >/dev/null || true
done

# ── Rotation : supprimer snapshots > RETENTION_HOURS ──────────────
find "$QDRANT_SNAPSHOTS" -name "*.snapshot" -mmin "+$((RETENTION_HOURS * 60))" -delete 2>/dev/null || true
log "Rotation: snapshots > ${RETENTION_HOURS}h supprimés"

# ── Rsync vers Node 2 (no-op si NODE2_IP vide) ────────────────────
if [[ -n "$NODE2_IP" ]]; then
  log "Sync vers Node 2: ${NODE2_SSH_USER}@${NODE2_IP}:${NODE2_SNAPSHOT_DIR}"
  rsync -az --delete \
    -e "ssh -i $NODE2_SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10" \
    "$QDRANT_SNAPSHOTS/" \
    "${NODE2_SSH_USER}@${NODE2_IP}:${NODE2_SNAPSHOT_DIR}/" \
  && log "OK sync Node 2" \
  || log "WARN: rsync Node 2 échoué (Node 2 non disponible ?)"
else
  log "NODE2_IP non défini — rsync désactivé (normal si Node 2 pas encore approvisionné)"
fi

if [[ $ERRORS -gt 0 ]]; then
  log "WARN: $ERRORS collection(s) en erreur"
  exit 1
fi

log "Snapshot terminé — ${QDRANT_SNAPSHOTS}/"
