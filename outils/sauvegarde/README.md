# Sauvegarde continue — outillage local

Cible S3-compatible (MinIO) pour développer/tester Litestream (SQLite) et WAL-G (Postgres)
sans dépendre d'un vrai compte cloud. Voir le plan complet :
`docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md`.

## Démarrer

    cd outils/sauvegarde && docker compose up -d

Console web MinIO : http://localhost:9001 (identifiants = SAUVEGARDE_S3_ACCESS_KEY /
SAUVEGARDE_S3_SECRET_KEY du `.env` racine).

## Arrêter

    cd outils/sauvegarde && docker compose down

## Production (HP)

Remplacer les 5 variables `SAUVEGARDE_S3_*` du `.env` racine par celles d'un vrai stockage
S3/B2 et ne PAS démarrer ce `docker-compose.yml` sur le HP — aucun autre changement requis
côté Litestream/WAL-G.
