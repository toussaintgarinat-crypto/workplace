#!/bin/bash
#
# Lancer le studio — démarre UNIQUEMENT ce qu'il faut pour le Studio audio-séries :
#   • gateway      (briques/gateway)        → fait répondre les 6 agents IA  (:4001)
#   • brique images(briques/images)          → portraits & couvertures        (:5950)
#   • brique video (briques/video)           → bande-annonce & animation       (:5970)
#   • stack Oria   (oria-stack/oria)         → interface + atelier            (:3003 / :8000)
#   • serveur voix (outils/studio-voix)      → produit l'audio say+ffmpeg     (:5810, sur l'hôte)
#
# Idempotent : ne démarre que ce qui manque, ne casse rien si c'est déjà en ligne.
# Honnêteté technique : on n'affiche « en ligne » que lorsque le point de santé répond.

set -uo pipefail

BLEU='\033[1;34m'; VERT='\033[1;32m'; JAUNE='\033[1;33m'; ROUGE='\033[1;31m'; GRIS='\033[0;90m'; RAZ='\033[0m'
ok()    { echo -e "  ${VERT}✔${RAZ} $1"; }
info()  { echo -e "  ${GRIS}·${RAZ} $1"; }
warn()  { echo -e "  ${JAUNE}!${RAZ} $1"; }
err()   { echo -e "  ${ROUGE}✗${RAZ} $1"; }
titre() { echo -e "\n${BLEU}▸ $1${RAZ}"; }

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

clear
echo -e "${BLEU}╔══════════════════════════════════════════════╗${RAZ}"
echo -e "${BLEU}║   STUDIO AUDIO-SÉRIES — démarrage ciblé        ║${RAZ}"
echo -e "${BLEU}╚══════════════════════════════════════════════╝${RAZ}"

# Attend qu'une URL réponde (HTTP < 500). 0 si OK avant le timeout.
attendre() {
  local url="$1" max="${2:-40}"
  for i in $(seq 1 "$max"); do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null)
    if [ -n "$code" ] && [ "$code" -lt 500 ] 2>/dev/null && [ "$code" != "000" ]; then return 0; fi
    sleep 1
  done
  return 1
}

# ── 1. Docker ────────────────────────────────────────────────────────────────
titre "Vérification de Docker"
if ! docker info >/dev/null 2>&1; then
  warn "Docker n'est pas démarré — ouverture de Docker Desktop…"
  open -a Docker 2>/dev/null
  for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  if ! docker info >/dev/null 2>&1; then
    err "Docker ne répond pas. Lance Docker Desktop à la main puis relance ce script."
    echo ""; read -r -p "Appuie sur Entrée pour fermer…" _; exit 1
  fi
fi
ok "Docker est prêt"

# ── 2. Gateway (agents IA) ───────────────────────────────────────────────────
titre "Gateway (agents IA)"
if attendre "http://localhost:4001/health" 1; then
  ok "déjà en ligne (:4001)"
else
  info "démarrage…"
  ( cd "$RACINE/briques/gateway" && docker compose up -d ) >/dev/null 2>&1
  if attendre "http://localhost:4001/health" 40; then ok "en ligne (:4001)"; else err "ne répond pas (:4001)"; fi
fi

# ── 2bis. Brique images (illustration : portraits, couvertures) ──────────────
titre "Brique images (illustration)"
if attendre "http://localhost:5950/sante" 1; then
  ok "déjà en ligne (:5950)"
else
  info "démarrage…"
  ( cd "$RACINE/briques/images" && docker compose up -d ) >/dev/null 2>&1
  if attendre "http://localhost:5950/sante" 40; then
    ok "en ligne (:5950) — mode placeholder tant que COMFY_URL n'est pas branché"
  else
    warn "ne répond pas (:5950) — la synergie images sera indisponible"
  fi
fi

# ── 2ter. Brique video (bande-annonce d'épisode, animation de portrait) ──────
titre "Brique video (génération vidéo)"
if attendre "http://localhost:5970/sante" 1; then
  ok "déjà en ligne (:5970)"
else
  info "démarrage…"
  ( cd "$RACINE/briques/video" && docker compose up -d ) >/dev/null 2>&1
  if attendre "http://localhost:5970/sante" 40; then
    ok "en ligne (:5970) — mode placeholder tant qu'aucun fournisseur vidéo n'est branché"
  else
    warn "ne répond pas (:5970) — la synergie vidéo sera indisponible"
  fi
fi

# ── 3. Stack Oria (interface + atelier) ──────────────────────────────────────
titre "Stack Oria (interface + atelier)"
if attendre "http://localhost:8000/health" 1; then
  ok "backend déjà en ligne (:8000)"
else
  info "démarrage (gros stack, patiente)…"
  ( cd "$RACINE/oria-stack/oria" && docker compose up -d ) >/dev/null 2>&1
  if attendre "http://localhost:8000/health" 90; then ok "backend en ligne (:8000)"; else warn "backend lent — vérifie http://localhost:3003 dans une minute"; fi
fi
if attendre "http://localhost:3003" 1; then ok "frontend en ligne (:3003)"; else warn "frontend pas encore prêt (:3003)"; fi

# ── 4. Serveur voix (sur l'hôte macOS) ───────────────────────────────────────
titre "Serveur voix (say + ffmpeg, sur l'hôte)"
if attendre "http://localhost:5810/sante" 1; then
  ok "déjà en ligne (:5810)"
else
  info "démarrage en arrière-plan…"
  ( cd "$RACINE/outils/studio-voix" && nohup python3 serveur.py >"$RACINE/outils/studio-voix/serveur.log" 2>&1 & )
  if attendre "http://localhost:5810/sante" 15; then
    ok "en ligne (:5810) — journal : outils/studio-voix/serveur.log"
  else
    err "ne répond pas (:5810) — voir outils/studio-voix/serveur.log"
  fi
fi

# ── 5. Ouverture du navigateur ───────────────────────────────────────────────
titre "Ouverture du Studio"
info "Oria → entre dans un monde → bouton « Atelier de série » 🎬"
open "http://localhost:3003" 2>/dev/null

echo ""
ok "Studio prêt."
echo ""
