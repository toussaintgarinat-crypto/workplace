#!/usr/bin/env bash
# Régénère app/models/generated.py depuis la DB Postgres forge LIVE (sqlacodegen).
#
# La source de vérité des tables reste forge/core/src/db/schema.ts (Drizzle) :
# on restreint la réflexion à ces tables pour ne PAS aspirer les tables Keycloak
# /Patroni de la base partagée.
#
# Usage :
#   ./scripts/gen_models.sh                 # via réseau docker forge_default
#   DBURL=postgresql+psycopg://u:p@host/db ./scripts/gen_models.sh   # DB explicite
#
# Prérequis sans DBURL : le conteneur forge-postgres tourne sur le réseau
# forge_default (make start côté forge).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCHEMA_TS="$ROOT/../core/src/db/schema.ts"
OUT="$ROOT/app/models/generated.py"

# Tables jamais créées dans l'instance courante (features non activées). À retirer
# de cette liste quand leurs migrations existent. Cf. en-tête de generated.py.
MISSING="audit_mission_poles hitl_requests mcp_servers metrics_snapshots pole_dev_requests repetition_configs repetition_events repetition_silences skills venture_delete_tokens"

echo "→ extraction des tables Drizzle depuis $SCHEMA_TS"
grep -oE "= pgTable\('([a-z_]+)'" "$SCHEMA_TS" | sed -E "s/= pgTable\('//; s/'//" | sort -u > /tmp/_forge_all.txt
printf '%s\n' $MISSING | sort -u > /tmp/_forge_missing.txt
grep -vxF -f /tmp/_forge_missing.txt /tmp/_forge_all.txt > /tmp/_forge_present.txt
TABLES=$(paste -sd, /tmp/_forge_present.txt)
echo "→ $(wc -l < /tmp/_forge_present.txt) tables à refléter"

HEADER=$(cat <<'EOF'
# ──────────────────────────────────────────────────────────────────────────
# AUTO-GÉNÉRÉ par sqlacodegen — NE PAS ÉDITER À LA MAIN.
#
# Sprint S126 (socle migration forge/core TS→Python). Reflète les tables
# Postgres existantes (source de vérité = Drizzle forge/core/src/db/schema.ts).
# La DB ne bouge pas pendant la migration strangler → ces modèles mappent le
# schéma tel quel, zéro migration de données.
#
# Régénérer :  ./scripts/gen_models.sh
#
# Tables non couvertes (features jamais activées, tables non encore créées) :
#   audit_mission_poles, hitl_requests, mcp_servers, metrics_snapshots,
#   pole_dev_requests, repetition_configs, repetition_events,
#   repetition_silences, skills, venture_delete_tokens
# ──────────────────────────────────────────────────────────────────────────
EOF
)

run_codegen() {
  sqlacodegen --generator declarative --tables "$TABLES" "$1"
}

if [ -n "${DBURL:-}" ]; then
  echo "→ génération via DBURL fourni"
  { echo "$HEADER"; run_codegen "$DBURL"; } > "$OUT"
else
  echo "→ génération via conteneur jetable sur réseau forge_default"
  TMP=$(mktemp)
  docker run --rm --network forge_default \
    -e DBURL="postgresql+psycopg://forge:forge_secret_change_this@postgres:5432/forge" \
    -e TABLES="$TABLES" \
    python:3.12-slim bash -c '
      pip install -q "sqlacodegen>=3.0.0" "psycopg[binary]" >/dev/null 2>&1
      sqlacodegen --generator declarative --tables "$TABLES" "$DBURL"
    ' > "$TMP"
  { echo "$HEADER"; cat "$TMP"; } > "$OUT"
  rm -f "$TMP"
fi

echo "✓ $OUT régénéré ($(grep -c '^class ' "$OUT") classes)"
