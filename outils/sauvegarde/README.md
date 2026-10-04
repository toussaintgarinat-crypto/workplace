# Sauvegardes Workplace

S236 : [exports cohérents et restauration isolée](coherent/README.md), [transport chiffré Duplicati](duplicati/README.md). Cibles : disque externe/USB, NAS ou serveur local/distant ; activation après configuration de la destination.

Le reste de ce document décrit le chantier historique Litestream/WAL-G et sa cible S3 de développement (SeaweedFS depuis S237b ; MinIO auparavant, image plus publiée).

## Sauvegarde continue — outillage local

Cible S3-compatible (SeaweedFS) pour développer/tester Litestream (SQLite) et WAL-G (Postgres)
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
d'erreur), le S3 démarre sans identité et `seaweedfs-init` échoue à créer le bucket.

Pas de console web. Vérifier que le S3 répond, **sur cette machine de développement** :

    curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9002/healthz

⚠️ Le port hôte est **9002**, pas 9000 : le port hôte 9000 est déjà pris par le conteneur
`workplace_peertube` sur cette machine. Depuis `proxy_net` (l'interface utilisée par
Litestream/WAL-G), l'endpoint est `http://seaweedfs:8333`. Sur une machine sans ce conflit
de port, adapter le mapping et cette commande.

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
