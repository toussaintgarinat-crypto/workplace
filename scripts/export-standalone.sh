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

# 4) manifest.json (décrit les capacités de l'agenda ; les tests de contrat le lisent).
#    Le Dockerfile standalone le COPY vers /manifest.json (emplacement attendu par les
#    tests une fois le layout aplati : backend/tests → /app/tests, parents[2] = /).
#    On ASSAINIT les champs Workplace-locaux avant de le publier (chemin auteur,
#    host.docker.internal, mention interne) — les capacités testées sont préservées.
python3 - "$SRC_ROOT/briques/agenda/manifest.json" "$DEST/manifest.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src))
d.pop("chemin_source", None)
d["url_sante"] = "http://localhost:8400/health"
if isinstance(d.get("description"), str):
    d["description"] = d["description"].replace(" (repris de workspace/calendar)", "")
json.dump(d, open(dst, "w"), ensure_ascii=False, indent=2)
PY

echo "Synchro OK -> $DEST (backend/ + vendor/ + manifest.json assaini)"
