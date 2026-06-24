#!/usr/bin/env bash
# Synchronise le socle « manipulation directe » (S101) dans chaque brique qui le sert.
#
# Pourquoi une copie ? Chaque brique est une image Docker autonome (build context =
# son propre dossier, `COPY . .`). Un fichier hors contexte n'entre pas dans l'image.
# La SOURCE UNIQUE reste shared/manipulation_directe.js ; on en pousse une copie
# (en lecture seule conceptuellement) dans chaque brique consommatrice. Relancer
# ce script après toute édition de la source.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="shared/manipulation_directe.js"
BRIQUES=(studio personnages restaurant)   # consommateurs actuels ; en ajouter au fil de S102/S104

for b in "${BRIQUES[@]}"; do
  cp "$SRC" "briques/$b/manipulation_directe.js"
  echo "→ briques/$b/manipulation_directe.js"
done

# Le Cœur sert aussi le socle (dashboard = future app web ; S102 menu contextuel).
# Son contexte de build est core/, donc il lui faut sa propre copie.
cp "$SRC" "core/manipulation_directe.js"
echo "→ core/manipulation_directe.js"

echo "Socle synchronisé dans $((${#BRIQUES[@]} + 1)) cible(s)."
