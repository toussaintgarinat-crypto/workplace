#!/usr/bin/env bash
# Synchronise le moteur holistique (briques/personnages) vers le dépôt standalone
# « Portrait Cosmique ». Workplace reste la SOURCE DE VÉRITÉ : ce script rafraîchit
# uniquement engine/ (les 3 modules de calcul + leurs tests), jamais les fichiers
# possédés par le standalone (main.py, llm.py, static/, Dockerfile, README, etc.) —
# ceux-là divergent volontairement (API/produit propres au standalone).
set -euo pipefail

DEST="${1:?usage: export-portrait-cosmique.sh <chemin-du-depot-standalone>}"
SRC="$(cd "$(dirname "$0")/.." && pwd)/briques/personnages"

EXCLUDES=(--exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache')

mkdir -p "$DEST/engine"

FICHIERS=(traditions.py synthese.py significations.py aspects.py dominantes.py
          ephemeride.py maisons.py theme_complet.py
          test_traditions.py test_synthese.py test_significations.py test_aspects.py
          test_dominantes.py test_ephemeride.py test_maisons.py test_theme_complet.py)

for f in "${FICHIERS[@]}"; do
    cp "$SRC/$f" "$DEST/engine/$f"
done

echo "Synchro OK -> $DEST/engine (${#FICHIERS[@]} fichiers, moteur holistique verbatim)"
