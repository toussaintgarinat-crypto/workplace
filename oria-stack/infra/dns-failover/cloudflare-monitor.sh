#!/usr/bin/env bash
# infra/dns-failover/cloudflare-monitor.sh
#
# Surveille Traefik HP et bascule les DNS Cloudflare vers Node 2 si HP tombe.
# Sur retour de HP, restaure les DNS automatiquement.
#
# Usage :
#   ./cloudflare-monitor.sh          # boucle daemon
#   ./cloudflare-monitor.sh --restore # force restore DNS vers HP et quitte
#
# Variables d'environnement requises (ou dans .env au répertoire racine) :
#   CF_API_TOKEN      Token Cloudflare (Zone DNS Edit)
#   CF_ZONE_ID        ID de la zone (onglet Overview du domaine dans CF)
#   CF_RECORDS        Enregistrements A séparés par virgules (ex: assistant.foo.fr,oria.foo.fr)
#   HP_PUBLIC_IP      IP publique HP G4 SFF (primaire)
#   NODE2_PUBLIC_IP   IP publique Node 2 (standby)
#
# Variables optionnelles :
#   HP_HEALTHZ_URL    URL healthcheck HP (défaut: http://HP_PUBLIC_IP:8082/ping)
#   FAIL_THRESHOLD    Nb d'échecs consécutifs avant bascule (défaut: 3)
#   POLL_INTERVAL     Intervalle de poll en secondes (défaut: 30)
#   STATE_FILE        Fichier d'état (défaut: /tmp/cf-monitor-state)
#   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — alertes Telegram

set -euo pipefail

# ── Charger .env si disponible ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_ENV="${SCRIPT_DIR}/../../.env"
[[ -f "$ROOT_ENV" ]] && set -a && source "$ROOT_ENV" && set +a

# ── Validation config ─────────────────────────────────────────────────────────
: "${CF_API_TOKEN:?CF_API_TOKEN requis}"
: "${CF_ZONE_ID:?CF_ZONE_ID requis}"
: "${CF_RECORDS:?CF_RECORDS requis (ex: assistant.domain.fr,oria.domain.fr)}"
: "${HP_PUBLIC_IP:?HP_PUBLIC_IP requis}"
: "${NODE2_PUBLIC_IP:?NODE2_PUBLIC_IP requis}"

HP_HEALTHZ_URL="${HP_HEALTHZ_URL:-http://${HP_PUBLIC_IP}:8082/ping}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
STATE_FILE="${STATE_FILE:-/tmp/cf-monitor-state}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /tmp/cf-monitor.log; }

telegram() {
  local msg="$1"
  [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_CHAT_ID" ]] && return 0
  curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=${msg}" \
    -d "parse_mode=HTML" > /dev/null 2>&1 || true
}

cf_get_record_id() {
  local name="$1"
  curl -sS "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records?name=${name}&type=A" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['id'])"
}

cf_update_record() {
  local name="$1" ip="$2" record_id="$3"
  local resp
  resp=$(curl -sS -X PUT \
    "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records/${record_id}" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"A\",\"name\":\"${name}\",\"content\":\"${ip}\",\"ttl\":60,\"proxied\":false}")
  if ! echo "$resp" | python3 -c "import sys,json; assert json.load(sys.stdin)['success']" 2>/dev/null; then
    log "  ✗ Erreur CF API pour $name: $resp"
    return 1
  fi
}

check_health() {
  curl -sf --max-time 10 "${HP_HEALTHZ_URL}" > /dev/null 2>&1
}

load_state() {
  FAIL_COUNT=0
  DNS_SWITCHED=0
  [[ -f "$STATE_FILE" ]] && source "$STATE_FILE"
}

save_state() {
  printf 'FAIL_COUNT=%d\nDNS_SWITCHED=%d\n' "$FAIL_COUNT" "$DNS_SWITCHED" > "$STATE_FILE"
}

switch_to_n2() {
  log "🚨 Bascule DNS → Node 2 (${NODE2_PUBLIC_IP}) après ${FAIL_THRESHOLD} échecs..."
  local failed=0
  IFS=',' read -ra records <<< "$CF_RECORDS"
  for rec in "${records[@]}"; do
    local rid
    rid=$(cf_get_record_id "$rec") || { log "  ✗ Impossible de récupérer l'ID de $rec"; failed=1; continue; }
    cf_update_record "$rec" "${NODE2_PUBLIC_IP}" "$rid" && log "  ✓ $rec → ${NODE2_PUBLIC_IP}" || failed=1
  done
  if [[ $failed -eq 0 ]]; then
    DNS_SWITCHED=1
    save_state
    telegram "🚨 <b>HP Traefik DOWN</b> — DNS basculé vers Node 2 (${NODE2_PUBLIC_IP}).
TTL 60s — propagation ~1min.
Vérifier : https://$(echo "$CF_RECORDS" | cut -d, -f1)/health"
  else
    log "  ✗ Bascule partielle — vérifier les erreurs ci-dessus"
    telegram "⚠️ <b>HP Traefik DOWN + bascule CF partielle</b> — intervention manuelle requise."
  fi
}

restore_to_hp() {
  log "✅ HP de retour — restauration DNS → HP (${HP_PUBLIC_IP})..."
  local failed=0
  IFS=',' read -ra records <<< "$CF_RECORDS"
  for rec in "${records[@]}"; do
    local rid
    rid=$(cf_get_record_id "$rec") || { log "  ✗ Impossible de récupérer l'ID de $rec"; failed=1; continue; }
    cf_update_record "$rec" "${HP_PUBLIC_IP}" "$rid" && log "  ✓ $rec → ${HP_PUBLIC_IP}" || failed=1
  done
  if [[ $failed -eq 0 ]]; then
    DNS_SWITCHED=0
    FAIL_COUNT=0
    save_state
    telegram "✅ <b>HP Traefik UP</b> — DNS restauré vers HP (${HP_PUBLIC_IP})."
  else
    log "  ✗ Restauration partielle — intervention manuelle requise"
    telegram "⚠️ <b>HP revenu mais restauration CF partielle</b> — vérifier les DNS manuellement."
  fi
}

# ── Mode --restore ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--restore" ]]; then
  log "Mode --restore : bascule forcée vers HP (${HP_PUBLIC_IP})"
  restore_to_hp
  exit 0
fi

# ── Boucle principale ─────────────────────────────────────────────────────────
log "cloudflare-monitor démarré"
log "  Poll : ${HP_HEALTHZ_URL} toutes les ${POLL_INTERVAL}s"
log "  Seuil bascule : ${FAIL_THRESHOLD} échecs consécutifs"
load_state

while true; do
  if check_health; then
    if [[ "${DNS_SWITCHED}" -eq 1 ]]; then
      restore_to_hp
    else
      if [[ "${FAIL_COUNT}" -gt 0 ]]; then
        log "✓ HP de nouveau joignable (fail_count reset)"
      fi
      FAIL_COUNT=0
      save_state
    fi
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    log "⚠️  Échec healthcheck #${FAIL_COUNT}/${FAIL_THRESHOLD} — ${HP_HEALTHZ_URL}"
    if [[ "${FAIL_COUNT}" -ge "${FAIL_THRESHOLD}" && "${DNS_SWITCHED}" -eq 0 ]]; then
      switch_to_n2
    fi
    save_state
  fi
  sleep "${POLL_INTERVAL}"
done
