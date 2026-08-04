# Sauvegarde continue — outillage local

Cible S3-compatible (MinIO) pour développer/tester Litestream (SQLite) et WAL-G (Postgres)
sans dépendre d'un vrai compte cloud. Voir le plan complet :
`docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md`.

## Démarrer

    cd outils/sauvegarde && docker compose --env-file ../../.env up -d

Le `--env-file ../../.env` est **obligatoire** : ce `docker-compose.yml` interpole
`${AWS_ACCESS_KEY_ID}` / `${AWS_SECRET_ACCESS_KEY}` / `${SAUVEGARDE_S3_BUCKET}`
directement (pas seulement `env_file:` dans un service). Or `docker compose` ne charge
automatiquement un `.env` que depuis le répertoire du projet (ici `outils/sauvegarde/`),
jamais depuis la racine du dépôt où vit le vrai `.env`. Sans `--env-file ../../.env`,
`docker compose config` résout ces variables en chaîne vide **silencieusement** (pas
d'erreur), MinIO démarre avec un utilisateur/mot de passe root vides, et `minio-init`
échoue à créer le bucket.

Console web MinIO : http://localhost:9001 (identifiants = AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY du `.env` racine).

Vérifier que MinIO répond, **sur cette machine de développement** :

    curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9002/minio/health/live

⚠️ Le port hôte est **9002**, pas 9000 : `docker-compose.yml` remappe l'API MinIO sur
`9002:9000` côté hôte parce que le port hôte 9000 est déjà pris par le conteneur
`workplace_peertube` sur cette machine (le port CONTENEUR reste 9000, donc
`http://minio:9000` depuis `proxy_net` — l'interface utilisée par Litestream/WAL-G — est
inchangé). **Piège vérifié** : `curl http://localhost:9000/minio/health/live` répond
quand même `200` sur cette machine — pas une erreur de connexion, mais la réponse HTML de
`workplace_peertube` (faux positif silencieux, ça n'est PAS MinIO). Toujours vérifier sur
9002 ici ; sur une machine sans ce conflit de port, adapter le mapping et cette commande.

## Arrêter

    cd outils/sauvegarde && docker compose --env-file ../../.env down

## Production (HP)

Une SEULE source de vérité pour les identifiants S3 (re-revue finale whole-branch, split-
brain `SAUVEGARDE_S3_*`/`AWS_*` éliminé, `.superpowers/sdd/progress.md`) : remplacer, dans
le `.env` racine, les 5 variables `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_ENDPOINT` / `AWS_REGION` / `SAUVEGARDE_S3_BUCKET` par celles d'un vrai stockage S3/B2,
et ne PAS démarrer ce `docker-compose.yml` sur le HP. Ces mêmes 5 variables sont lues telles
quelles par Litestream (`donnees`/`agenda`) et WAL-G (`memoire-db`, `gateway/db`) via
`env_file:` — aucun autre changement requis, il n'y a plus qu'un seul jeu de noms à éditer.
