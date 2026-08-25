#!/usr/bin/env bash
# S125 — préflight de bascule sur le HP (cf. MIGRATION-HP.md).
# Vérifie les prérequis AVANT de builder le stack et de rejouer les preuves LIVE.
# Lecture seule : ne démarre rien, ne modifie rien. Sort != 0 si un prérequis dur manque.
set -u

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE" || exit 2

ok() { printf "  ✅ %s\n" "$1"; }
warn() { printf "  ⚠️  %s\n" "$1"; AVERT=$((AVERT+1)); }
ko() { printf "  ❌ %s\n" "$1"; DUR=$((DUR+1)); }

# Exécute une commande avec un plafond de temps (évite qu'un daemon Docker en vrac fige
# le préflight). Utilise timeout/gtimeout si présents, sinon exécute sans plafond.
_borne() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"
  else "$@"; fi
}

DUR=0; AVERT=0
DISQUE_MIN_GO=20

echo "── Préflight HP (racine : $RACINE) ─────────────────────────────"

# 1. Docker présent et démarré
echo "Docker :"
if command -v docker >/dev/null 2>&1; then
  if _borne 10 docker info >/dev/null 2>&1; then ok "daemon Docker actif"
  else ko "Docker installé mais daemon injoignable/figé (démarrer Docker)"; fi
  docker compose version >/dev/null 2>&1 && ok "docker compose v2 dispo" \
    || ko "docker compose v2 absent (plugin compose requis)"
else
  ko "docker introuvable dans le PATH"
fi

# 2. Disque libre (pour les builds d'images)
echo "Disque :"
LIBRE_KO=$(df -Pk . | awk 'NR==2 {print $4}')
LIBRE_GO=$(( LIBRE_KO / 1024 / 1024 ))
if [ "$LIBRE_GO" -ge "$DISQUE_MIN_GO" ]; then ok "${LIBRE_GO} Go libres (≥ ${DISQUE_MIN_GO})"
else warn "${LIBRE_GO} Go libres (< ${DISQUE_MIN_GO}) — risque d'ENOSPC ; 'docker system prune -af'"; fi

# 3. Fichiers .env requis
echo "Secrets (.env) :"
REQUIS=(
  ".env"
  "briques/gateway/.env"
  "briques/forge/.env"
  "briques/forge/forge/.env"
  "briques/agenda/.env"
  "briques/agenda/backend/.env"
  "briques/donnees/.env:opt"   # optionnel : donnees tourne auth-off sans .env
  "oria-stack/infra/keycloak/.env:opt"  # requis seulement pour le Niveau B
  "briques/world-engine/.env:opt"  # optionnel : 2e tenant API_KEYS, voir mesure de charge Sprint E
)
for entree in "${REQUIS[@]}"; do
  f="${entree%%:*}"; flag="${entree##*:}"
  if [ -f "$f" ]; then ok "$f"
  elif [ "$flag" = "opt" ]; then warn "$f absent (optionnel : voir MIGRATION-HP.md)"
  else ko "$f MANQUANT (copier/remplir depuis le gabarit .env.example)"; fi
done

# 4. shared/ présent (lib partagée embarquée au build)
echo "Lib partagée :"
[ -f "shared/workplace_auth.py" ] && ok "shared/workplace_auth.py" \
  || ko "shared/workplace_auth.py absent (clone incomplet ?)"
[ -f "shared/llm_client.py" ] && ok "shared/llm_client.py" \
  || ko "shared/llm_client.py absent"

# 5. Ports clés libres (informatif)
echo "Ports (informatif) :"
for port in 4001 5100 5500 8400 5700 8080; do
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "port $port déjà occupé (un service tourne peut-être déjà)"
  else ok "port $port libre"; fi
done

echo "────────────────────────────────────────────────────────────────"
if [ "$DUR" -gt 0 ]; then
  printf "Préflight : %d bloquant(s), %d avertissement(s). Corriger avant de builder.\n" "$DUR" "$AVERT"
  exit 1
fi
printf "Préflight OK : 0 bloquant, %d avertissement(s). Prêt pour 'docker compose up -d --build'.\n" "$AVERT"
exit 0
