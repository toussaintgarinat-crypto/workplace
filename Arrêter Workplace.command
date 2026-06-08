#!/bin/bash
#
# Arrêter Workplace — éteint proprement le Cœur, l'assistant et les briques.
#
# Double-clique ce fichier. Il arrête chaque stack (ordre inverse du démarrage)
# sans supprimer les données (les volumes Postgres/mémoire sont conservés).

set -uo pipefail

VERT='\033[1;32m'; JAUNE='\033[1;33m'; GRIS='\033[0;90m'; BLEU='\033[1;34m'; RAZ='\033[0m'
ok()   { echo -e "  ${VERT}✔${RAZ} $1"; }
warn() { echo -e "  ${JAUNE}!${RAZ} $1"; }
info() { echo -e "  ${GRIS}·${RAZ} $1"; }

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

clear
echo -e "${BLEU}╔══════════════════════════════════════════════╗${RAZ}"
echo -e "${BLEU}║         WORKPLACE — arrêt des briques         ║${RAZ}"
echo -e "${BLEU}╚══════════════════════════════════════════════╝${RAZ}"
echo ""

if ! docker info >/dev/null 2>&1; then
  warn "Docker n'est pas en cours d'exécution — rien à arrêter."
  echo ""; read -r -p "Appuie sur Entrée pour fermer…" _; exit 0
fi

# Ordre inverse du démarrage : on coupe le Cœur d'abord.
DOSSIERS=(
  "core|$RACINE/core"
  "oria|$RACINE/oria-stack/oria"
  "agenda|$RACINE/briques/agenda"
  "generateur|$RACINE/briques/generateur"
  "audit|$RACINE/briques/audit"
  "donnees|$RACINE/briques/donnees"
  "etl|$RACINE/briques/etl"
  "forge|$RACINE/briques/forge"
  "memoire|$RACINE/briques/memoire"
  "gateway|$RACINE/briques/gateway"
)

for ligne in "${DOSSIERS[@]}"; do
  IFS='|' read -r nom dossier <<< "$ligne"
  if [ -d "$dossier" ] && ls "$dossier"/docker-compose*.y*ml >/dev/null 2>&1; then
    info "Arrêt de « $nom »…"
    ( cd "$dossier" && docker compose down ) >/dev/null 2>&1 && ok "« $nom » arrêtée" || warn "« $nom » : rien à arrêter"
  fi
done

echo ""
ok "Workplace est arrêté. Les données sont conservées (relance avec « Lancer Workplace.command »)."
echo ""
read -r -p "Appuie sur Entrée pour fermer cette fenêtre…" _
