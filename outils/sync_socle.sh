#!/usr/bin/env bash
# Synchronise les ASSETS FRONT PARTAGÉS dans chaque brique qui les sert.
#
# Pourquoi des copies ? Chaque brique est une image Docker autonome (build
# context = son propre dossier, `COPY . .`). Un fichier hors contexte n'entre
# pas dans l'image. Les SOURCES UNIQUES restent dans shared/ ; on en pousse une
# copie (en lecture seule conceptuellement) dans chaque brique consommatrice.
# Relancer ce script après toute édition d'une source.
#
#  • shared/manipulation_directe.js  (socle S101 : menu/modale/cliquer-déposer)
#  • shared/static/workplace.css     (design system S123 : tokens partagés)
set -euo pipefail
cd "$(dirname "$0")/.."

SOCLE="shared/manipulation_directe.js"
CSS="shared/static/workplace.css"

# Consommateurs du socle JS (dashboards riches : menu contextuel + drag).
SOCLE_BRIQUES=(studio personnages restaurant)
# Consommateurs du design system CSS (briques servant un front.html autoporté).
CSS_BRIQUES=(synopsis voix personnages studio transcription atelier-veille)

n=0
for b in "${SOCLE_BRIQUES[@]}"; do
  cp "$SOCLE" "briques/$b/manipulation_directe.js"
  echo "→ briques/$b/manipulation_directe.js"; n=$((n+1))
done
# Le Cœur sert aussi le socle (dashboard) ; contexte de build = core/.
cp "$SOCLE" "core/manipulation_directe.js"
echo "→ core/manipulation_directe.js"; n=$((n+1))

for b in "${CSS_BRIQUES[@]}"; do
  cp "$CSS" "briques/$b/workplace.css"
  echo "→ briques/$b/workplace.css"; n=$((n+1))
done
# Le Cœur sert aussi le design system (dashboard) ; contexte de build = core/.
cp "$CSS" "core/workplace.css"
echo "→ core/workplace.css"; n=$((n+1))

echo "Assets front synchronisés dans $n cible(s)."
