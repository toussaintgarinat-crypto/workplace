#!/usr/bin/env bash
# Synchronise le code de la brique agenda vers le dépôt standalone Calendrier Familial.
# La brique Workplace reste la SOURCE DE VÉRITÉ ; ce script rafraîchit uniquement le
# code copié (backend/ + vendor/), jamais les fichiers wrapper du dépôt standalone
# (Dockerfile, docker-compose.yml, entrypoint.sh, README.md, LICENSE, keycloak/).
set -euo pipefail

DEST="${1:?usage: export-standalone.sh <chemin-du-depot-standalone>}"
SRC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # racine Workplace

EXCLUDES=(--exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache'
          --exclude='*.db' --exclude='*.db-journal' --exclude='data')

mkdir -p "$DEST/backend" "$DEST/vendor/agent_personnel_shared" "$DEST/vendor/shared"

# 1) backend = copie verbatim
rsync -a --delete "${EXCLUDES[@]}" "$SRC_ROOT/briques/agenda/backend/" "$DEST/backend/"

# 2) paquet vendored agent_personnel_shared
rsync -a --delete "${EXCLUDES[@]}" "$SRC_ROOT/briques/agenda/shared/" "$DEST/vendor/agent_personnel_shared/"

# 3) le seul fichier externe utilisé + un __init__ minimal (pas de llm_client)
cp "$SRC_ROOT/shared/workplace_auth.py" "$DEST/vendor/shared/workplace_auth.py"
cat > "$DEST/vendor/shared/__init__.py" <<'PY'
"""Sous-ensemble vendoré de la lib partagée Workplace (workplace_auth uniquement)."""
PY

echo "Synchro OK -> $DEST (backend/ + vendor/)"
