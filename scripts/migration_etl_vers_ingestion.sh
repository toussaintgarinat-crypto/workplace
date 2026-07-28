#!/usr/bin/env bash
# S215 — recopie le volume Docker de l'ancienne brique `etl` dans celui d'`ingestion`.
#
# POURQUOI CE SCRIPT EXISTE. Le renommage de la brique renomme aussi son dossier, donc le
# nom de projet Compose, donc le volume : `etl_etl_data` → `ingestion_ingestion_data`. Un
# `docker compose up` sur le nouveau compose crée un volume NEUF et vide. La brique
# démarre parfaitement, répond `documents_ingeres: 0`, et les documents déjà ingérés sont
# toujours là — dans un volume que plus personne ne monte. Rien ne signale la perte.
#
# `stockage.reprendre_base_heritee()` ne suffit pas : elle sait renommer `etl.db` en
# `ingestion.db` DANS un volume, pas faire traverser deux volumes à un fichier.
#
# À LANCER AVANT le premier `up` de la brique renommée, sur toute machine où `etl`
# tournait déjà (le HP). Idempotent : relançable sans risque, il refuse d'écraser une
# base déjà en service.
#
# Usage :  scripts/migration_etl_vers_ingestion.sh [--verifier]
#            --verifier : n'écrit rien, dit seulement ce qui serait fait.

set -euo pipefail

ANCIEN="${VOLUME_ANCIEN:-etl_etl_data}"
NOUVEAU="${VOLUME_NOUVEAU:-ingestion_ingestion_data}"
VERIFIER=0
[ "${1:-}" = "--verifier" ] && VERIFIER=1

if ! docker info >/dev/null 2>&1; then
  echo "✗ Docker ne répond pas."
  exit 2
fi

existe() { docker volume inspect "$1" >/dev/null 2>&1; }

if ! existe "$ANCIEN"; then
  echo "→ Volume '$ANCIEN' absent : rien à migrer (installation neuve, ou migration déjà faite)."
  echo "  Volumes vus :"
  docker volume ls --format '  {{.Name}}' | grep -iE 'etl|ingestion' || echo "  (aucun)"
  exit 0
fi

# Une base déjà remplie côté nouveau volume = la brique renommée a déjà tourné et ingéré.
# L'écraser ferait reculer le déploiement d'un état complet — on s'arrête net.
if existe "$NOUVEAU" && docker run --rm -v "$NOUVEAU":/dest alpine:3.20 \
     test -s /dest/ingestion.db 2>/dev/null; then
  echo "✗ '$NOUVEAU' contient déjà une base 'ingestion.db' non vide."
  echo "  Migration ANNULÉE — elle écraserait des documents ingérés après le renommage."
  echo "  Si c'est bien ce que tu veux : supprime d'abord le volume ('docker volume rm $NOUVEAU')."
  exit 1
fi

echo "→ Contenu de '$ANCIEN' :"
docker run --rm -v "$ANCIEN":/src alpine:3.20 ls -la /src

if [ "$VERIFIER" = 1 ]; then
  echo ""
  echo "→ [--verifier] Rien n'a été écrit. La migration copierait /src/. vers '$NOUVEAU',"
  echo "  puis renommerait 'etl.db' en 'ingestion.db'."
  exit 0
fi

docker volume create "$NOUVEAU" >/dev/null

# Copie puis renommage dans le MÊME conteneur : à aucun moment la nouvelle base n'existe
# à moitié. `cp -a` préserve les dates, utile pour comparer après coup.
docker run --rm -v "$ANCIEN":/src:ro -v "$NOUVEAU":/dest alpine:3.20 sh -c '
  cp -a /src/. /dest/
  if [ -f /dest/etl.db ] && [ ! -f /dest/ingestion.db ]; then
    mv /dest/etl.db /dest/ingestion.db
  fi
'

echo ""
echo "→ Contenu de '$NOUVEAU' après migration :"
docker run --rm -v "$NOUVEAU":/dest alpine:3.20 ls -la /dest

echo ""
echo "✓ Migration faite. L'ancien volume '$ANCIEN' est LAISSÉ EN PLACE : c'est le filet"
echo "  de retour arrière. Le supprimer une fois la brique prouvée en ligne :"
echo "      docker volume rm $ANCIEN"
