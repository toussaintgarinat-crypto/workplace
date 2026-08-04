# Sauvegarde continue (RPO quelques secondes) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Réduire la perte de données possible (RPO) sur les 4 briques prioritaires (`memoire`, `donnees`, `gateway`, `agenda`) de "dernière sauvegarde périodique" (potentiellement des jours) à quelques secondes, via de la réplication/archivage continu vers un stockage S3-compatible — testable en local avant tout déploiement HP.

**Architecture:** Deux mécanismes selon le moteur de base :
- SQLite (`donnees`, `agenda`) → sidecar Litestream par brique, réplique en continu (`sync-interval: 1s`) vers un bucket S3, sans toucher à l'image applicative.
- Postgres (`memoire`, `gateway`) → WAL-G installé dans l'image Postgres, `archive_command` qui expédie chaque segment WAL vers le même bucket au fil de l'eau.

Un MinIO local (`outils/sauvegarde/`) sert de cible S3-compatible pour développement/test, sur le réseau partagé `proxy_net` déjà utilisé par `core`/`gateway`/`agenda`. En production (HP), les mêmes variables d'environnement pointeront vers un vrai stockage S3/B2 — aucun changement de code, seulement le `.env`.

**Tech Stack:** Litestream 0.5.15, WAL-G v3.0.8, MinIO (image `minio/minio` + client `minio/mc`), Docker Compose.

## Global Constraints

- Ne pas toucher aux ~15 autres briques SQLite ni à Oria/Patroni dans ce plan — hors périmètre, décidé explicitement avec l'utilisateur (voir note de limite en fin de plan).
- Toutes les nouvelles variables d'environnement vont dans `.env.example` (racine), commentées, jamais avec de vraie valeur secrète en clair.
- Suivre le motif `env_file: - path: ../../.env` déjà utilisé par toutes les briques (jamais redéclarer une variable en `VAR=${VAR:-}` dans un service qui n'en a pas besoin — piège "env shadow" documenté dans le repo).
- Tags d'image toujours épinglés (jamais `:latest`), conforme à la convention déjà en place sur tout le monorepo.
- Chaque tâche doit se vérifier par une commande dont la sortie est donnée dans le step — pas de "vérifier que ça marche" sans la commande exacte.

---

## Recherche déjà faite (pour ne pas la refaire)

- `pgvector/pgvector:0.8.2-pg16` (image de `memoire-db`) tourne sur **Debian bookworm**, glibc — compatible avec le binaire WAL-G officiel `wal-g-pg-22.04-amd64.tar.gz`.
- `postgres:16.14-alpine` (image actuelle de `gateway`/`db`) tourne sur **Alpine/musl** — **incompatible** avec ce même binaire. Le plan bascule ce service vers `postgres:16.14-bookworm` (même version majeure/mineure, juste la variante Debian) pour rester compatible WAL-G.
- Binaire WAL-G confirmé disponible : release `v3.0.8`, asset `wal-g-pg-22.04-amd64.tar.gz` (`https://github.com/wal-g/wal-g/releases/download/v3.0.8/wal-g-pg-22.04-amd64.tar.gz`).
- Image Litestream confirmée : `litestream/litestream:0.5.15` (déjà tirée en local avec succès).
- `donnees` : service `donnees`, volume `donnees_data:/data`, fichier `/data/donnees.db` (SQLite).
- `agenda` : service `agenda`, volume `agenda_data:/data`, fichier par défaut `/data/calendar.db` (SQLite, `DATABASE_URL` vide).
- `memoire` : service `memoire-db`, volume `memoire_pgdata:/var/lib/postgresql/data`, DB `memory`.
- `gateway` : service `db`, volume `gateway_db:/var/lib/postgresql/data`, DB `litellm`.
- Réseau partagé déjà existant : `proxy_net` (externe, créé une fois via `docker network create proxy_net` — déjà fait sur cette machine). `core`, `gateway`, `agenda` s'y attachent déjà.

---

## File Structure

- Create: `outils/sauvegarde/docker-compose.yml` — MinIO + init du bucket (dev/test).
- Create: `outils/sauvegarde/README.md` — comment démarrer/arrêter la cible S3 locale.
- Create: `briques/donnees/litestream.yml` — config de réplication SQLite → S3.
- Modify: `briques/donnees/docker-compose.yml` — sidecar `litestream`.
- Create: `briques/agenda/litestream.yml` — config de réplication SQLite → S3.
- Modify: `briques/agenda/docker-compose.yml` — sidecar `litestream`.
- Create: `briques/memoire/Dockerfile.walg` — image `memoire-db` + binaire WAL-G.
- Modify: `briques/memoire/docker-compose.yml` — build custom + `archive_command`.
- Create: `briques/gateway/Dockerfile.walg` — image `db` (bookworm) + binaire WAL-G.
- Modify: `briques/gateway/docker-compose.yml` — build custom + `archive_command`.
- Create: `outils/sauvegarde/restaurer_sqlite.sh` — restauration générique Litestream (donnees/agenda).
- Create: `outils/sauvegarde/restaurer_postgres.sh` — restauration générique WAL-G (memoire/gateway).
- Modify: `.env.example` — nouvelles variables `SAUVEGARDE_S3_*`.

---

### Task 1: Cible S3 locale (MinIO) pour développement/test

**Files:**
- Create: `outils/sauvegarde/docker-compose.yml`
- Create: `outils/sauvegarde/README.md`
- Modify: `.env.example`

**Interfaces:**
- Produces: un endpoint S3 joignable à `http://minio:9000` depuis n'importe quel conteneur attaché à `proxy_net`, et `http://localhost:9000` depuis l'hôte. Bucket `workplace-sauvegardes` déjà créé. Variables `SAUVEGARDE_S3_ENDPOINT`, `SAUVEGARDE_S3_BUCKET`, `SAUVEGARDE_S3_ACCESS_KEY`, `SAUVEGARDE_S3_SECRET_KEY`, `SAUVEGARDE_S3_REGION` lues depuis `.env` racine par toutes les tâches suivantes.

- [ ] **Step 1: Ajouter les variables de sauvegarde à `.env.example`**

Ajouter à la fin de `/Users/garinat_t/Desktop/Workplace/.env.example` :

```bash
# ── Sauvegarde continue (RPO quelques secondes, cf. docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md) ──
# En local/dev : MinIO démarré par outils/sauvegarde/docker-compose.yml, endpoint interne
# (depuis un conteneur sur proxy_net) = http://minio:9000. En prod (HP) : pointer vers un
# vrai stockage S3/B2 et remplacer ces 5 valeurs, aucun code à changer.
SAUVEGARDE_S3_ENDPOINT=http://minio:9000
SAUVEGARDE_S3_BUCKET=workplace-sauvegardes
SAUVEGARDE_S3_ACCESS_KEY=GENERER_openssl_rand_-hex_16
SAUVEGARDE_S3_SECRET_KEY=GENERER_openssl_rand_-hex_24
SAUVEGARDE_S3_REGION=us-east-1
```

- [ ] **Step 2: Copier ces valeurs dans le `.env` réel avec de vraies valeurs**

```bash
cd /Users/garinat_t/Desktop/Workplace
python3 - <<'EOF'
import secrets
print("SAUVEGARDE_S3_ACCESS_KEY=" + secrets.token_hex(16))
print("SAUVEGARDE_S3_SECRET_KEY=" + secrets.token_hex(24))
EOF
```

Copier les deux lignes générées, plus `SAUVEGARDE_S3_ENDPOINT=http://minio:9000`,
`SAUVEGARDE_S3_BUCKET=workplace-sauvegardes`, `SAUVEGARDE_S3_REGION=us-east-1`, à la fin du
`.env` racine (pas `.env.example` — celui-ci contient déjà les vraies valeurs secrètes).

- [ ] **Step 3: Créer `outils/sauvegarde/docker-compose.yml`**

```yaml
# MinIO = cible S3-compatible LOCALE pour développement/test des chantiers de sauvegarde
# continue (Litestream, WAL-G). En production (HP), un vrai stockage S3/B2 remplace ceci
# — seules les variables SAUVEGARDE_S3_* du .env racine changent, aucun code.
services:
  minio:
    image: minio/minio:RELEASE.2026-07-23T20-49-06Z
    container_name: workplace_minio
    environment:
      - MINIO_ROOT_USER=${SAUVEGARDE_S3_ACCESS_KEY}
      - MINIO_ROOT_PASSWORD=${SAUVEGARDE_S3_SECRET_KEY}
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    networks:
      - default
      - proxy_net
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  # Conteneur jetable : crée le bucket au premier démarrage puis s'arrête (exit 0 normal).
  minio-init:
    image: minio/mc:RELEASE.2026-07-16T18-52-24Z
    container_name: workplace_minio_init
    depends_on:
      minio:
        condition: service_healthy
    networks:
      - default
    entrypoint: >
      sh -c "
      mc alias set local http://minio:9000 ${SAUVEGARDE_S3_ACCESS_KEY} ${SAUVEGARDE_S3_SECRET_KEY} &&
      mc mb -p local/${SAUVEGARDE_S3_BUCKET} &&
      echo 'Bucket pret'
      "

volumes:
  minio_data:

networks:
  default:
  proxy_net:
    external: true
    name: proxy_net
```

- [ ] **Step 4: Créer `outils/sauvegarde/README.md`**

```markdown
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
```

- [ ] **Step 5: Démarrer et vérifier**

Run: `cd /Users/garinat_t/Desktop/Workplace/outils/sauvegarde && docker compose up -d`
Expected: les 2 services démarrent, `minio-init` se termine avec `Bucket pret` dans ses logs.

Run: `docker logs workplace_minio_init`
Expected: dernière ligne = `Bucket pret`

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9000/minio/health/live`
Expected: `200`

- [ ] **Step 6: Commit**

```bash
git add outils/sauvegarde/docker-compose.yml outils/sauvegarde/README.md .env.example
git commit -m "feat(sauvegarde): MinIO local pour tester Litestream/WAL-G"
```

---

### Task 2: Réplication continue de `donnees` (SQLite) avec Litestream

**Files:**
- Create: `briques/donnees/litestream.yml`
- Modify: `briques/donnees/docker-compose.yml`

**Interfaces:**
- Consumes: `SAUVEGARDE_S3_ENDPOINT/BUCKET/ACCESS_KEY/SECRET_KEY/REGION` (Task 1), bucket déjà créé.
- Produces: réplication continue de `/data/donnees.db` vers `s3://workplace-sauvegardes/donnees/`, retard cible ≤ quelques secondes (`sync-interval: 1s`).

- [ ] **Step 1: Créer `briques/donnees/litestream.yml`**

```yaml
dbs:
  - path: /data/donnees.db
    replicas:
      - type: s3
        endpoint: ${SAUVEGARDE_S3_ENDPOINT}
        bucket: ${SAUVEGARDE_S3_BUCKET}
        path: donnees
        region: ${SAUVEGARDE_S3_REGION}
        access-key-id: ${SAUVEGARDE_S3_ACCESS_KEY}
        secret-access-key: ${SAUVEGARDE_S3_SECRET_KEY}
        force-path-style: true
        sync-interval: 1s
```

- [ ] **Step 2: Ajouter le sidecar dans `briques/donnees/docker-compose.yml`**

Modifier `/Users/garinat_t/Desktop/Workplace/briques/donnees/docker-compose.yml` : ajouter le
service `litestream` après `donnees`, et déclarer les réseaux en bas de fichier (absents
aujourd'hui — seul `default` implicite existe) :

```yaml
  litestream:
    image: litestream/litestream:0.5.15
    container_name: workplace_donnees_litestream
    depends_on:
      donnees:
        condition: service_healthy
    env_file:
      - path: ../../.env
        required: false
    volumes:
      - donnees_data:/data
      - ./litestream.yml:/etc/litestream.yml:ro
    networks:
      - default
      - proxy_net
    command: ["replicate"]
    restart: unless-stopped
```

Et remplacer le bloc `volumes:` final par :

```yaml
volumes:
  donnees_data:

networks:
  default:
  proxy_net:
    external: true
    name: proxy_net
```

- [ ] **Step 3: Démarrer et vérifier la réplication initiale**

Run: `cd /Users/garinat_t/Desktop/Workplace/briques/donnees && docker compose up -d`
Expected: `donnees` et `litestream` démarrent (`workplace_donnees_litestream` doit rester
`Up`, pas `Restarting`).

Run: `sleep 5 && docker logs workplace_donnees_litestream --tail 20`
Expected: une ligne contenant `initialized db` puis `replicating to` sans erreur `ERROR`.

Run: `docker run --rm --network proxy_net -e MC_HOST_local="http://${SAUVEGARDE_S3_ACCESS_KEY}:${SAUVEGARDE_S3_SECRET_KEY}@minio:9000" minio/mc:RELEASE.2026-07-16T18-52-24Z ls local/workplace-sauvegardes/donnees/`
Expected: au moins un objet listé (générations Litestream), preuve que la réplication initiale a bien été poussée.

- [ ] **Step 4: Preuve bout-en-bout — écrire une donnée, la retrouver dans la réplique**

Run:
```bash
docker exec workplace_donnees python3 -c "
import sqlite3
c = sqlite3.connect('/data/donnees.db')
c.execute('CREATE TABLE IF NOT EXISTS preuve_rpo (id INTEGER PRIMARY KEY, valeur TEXT)')
c.execute('INSERT INTO preuve_rpo (valeur) VALUES (\"litestream-ok\")')
c.commit()
"
sleep 3
docker exec workplace_donnees_litestream litestream generations /data/donnees.db
```
Expected: la commande `litestream generations` liste au moins une génération avec un
timestamp postérieur à l'insertion (preuve que le changement a bien été capté en moins de
`sync-interval` + quelques secondes).

- [ ] **Step 5: Commit**

```bash
git add briques/donnees/litestream.yml briques/donnees/docker-compose.yml
git commit -m "feat(donnees): réplication continue SQLite→S3 via Litestream"
```

---

### Task 3: Réplication continue de `agenda` (SQLite) avec Litestream

**Files:**
- Create: `briques/agenda/litestream.yml`
- Modify: `briques/agenda/docker-compose.yml`

**Interfaces:**
- Consumes: identique à la Task 2 (variables `SAUVEGARDE_S3_*`).
- Produces: réplication continue de `/data/calendar.db` vers `s3://workplace-sauvegardes/agenda/`.

- [ ] **Step 1: Créer `briques/agenda/litestream.yml`**

```yaml
dbs:
  - path: /data/calendar.db
    replicas:
      - type: s3
        endpoint: ${SAUVEGARDE_S3_ENDPOINT}
        bucket: ${SAUVEGARDE_S3_BUCKET}
        path: agenda
        region: ${SAUVEGARDE_S3_REGION}
        access-key-id: ${SAUVEGARDE_S3_ACCESS_KEY}
        secret-access-key: ${SAUVEGARDE_S3_SECRET_KEY}
        force-path-style: true
        sync-interval: 1s
```

- [ ] **Step 2: Ajouter le sidecar dans `briques/agenda/docker-compose.yml`**

`agenda` a déjà `proxy_net` déclaré — ajouter seulement le service, juste après `agenda` :

```yaml
  litestream:
    image: litestream/litestream:0.5.15
    container_name: workplace_agenda_litestream
    depends_on:
      agenda:
        condition: service_healthy
    env_file:
      - path: ../../.env
        required: false
    volumes:
      - agenda_data:/data
      - ./litestream.yml:/etc/litestream.yml:ro
    networks:
      - default
      - proxy_net
    command: ["replicate"]
    restart: unless-stopped
```

- [ ] **Step 3: Démarrer et vérifier**

Run: `cd /Users/garinat_t/Desktop/Workplace/briques/agenda && docker compose up -d`
Expected: `workplace_agenda_litestream` reste `Up`.

Run: `sleep 5 && docker logs workplace_agenda_litestream --tail 20`
Expected: `initialized db` puis `replicating to`, pas de ligne `ERROR`.

Run: `docker run --rm --network proxy_net -e MC_HOST_local="http://${SAUVEGARDE_S3_ACCESS_KEY}:${SAUVEGARDE_S3_SECRET_KEY}@minio:9000" minio/mc:RELEASE.2026-07-16T18-52-24Z ls local/workplace-sauvegardes/agenda/`
Expected: au moins un objet listé.

- [ ] **Step 4: Commit**

```bash
git add briques/agenda/litestream.yml briques/agenda/docker-compose.yml
git commit -m "feat(agenda): réplication continue SQLite→S3 via Litestream"
```

---

### Task 4: Archivage WAL continu de `memoire` (Postgres) avec WAL-G

**Files:**
- Create: `briques/memoire/Dockerfile.walg`
- Modify: `briques/memoire/docker-compose.yml`

**Interfaces:**
- Consumes: variables `SAUVEGARDE_S3_*` (Task 1).
- Produces: chaque segment WAL de `memoire-db` expédié vers `s3://workplace-sauvegardes/memoire-wal/` en continu (retard = durée d'écriture d'un segment WAL, typiquement quelques secondes sous charge normale).

- [ ] **Step 1: Créer `briques/memoire/Dockerfile.walg`**

```dockerfile
# Image memoire-db + binaire WAL-G (archivage WAL continu, cf. plan
# docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md). Base Debian bookworm
# (confirmé) — compatible avec le binaire glibc officiel de WAL-G.
FROM pgvector/pgvector:0.8.2-pg16

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL -o /tmp/wal-g.tar.gz \
       https://github.com/wal-g/wal-g/releases/download/v3.0.8/wal-g-pg-22.04-amd64.tar.gz \
    && tar -xzf /tmp/wal-g.tar.gz -C /tmp \
    && mv /tmp/wal-g-pg-22.04-amd64 /usr/local/bin/wal-g \
    && chmod +x /usr/local/bin/wal-g \
    && rm /tmp/wal-g.tar.gz \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Modifier `briques/memoire/docker-compose.yml`**

Remplacer la ligne `image: pgvector/pgvector:0.8.2-pg16` du service `memoire-db` par un
build, et ajouter les variables WAL-G + `archive_command` :

```yaml
  memoire-db:
    build:
      context: .
      dockerfile: Dockerfile.walg
    image: workplace/memoire-db-walg:0.1.0   # tag épinglé (pas de :latest flottant, cf. convention du parc)
    environment:
      POSTGRES_USER: memory
      POSTGRES_PASSWORD: ${MEMOIRE_DB_PASSWORD:-memory}
      POSTGRES_DB: memory
      # WAL-G — expédition continue des WAL vers S3 (cf. plan sauvegarde continue).
      WALG_S3_PREFIX: s3://${SAUVEGARDE_S3_BUCKET}/memoire-wal
      AWS_ACCESS_KEY_ID: ${SAUVEGARDE_S3_ACCESS_KEY}
      AWS_SECRET_ACCESS_KEY: ${SAUVEGARDE_S3_SECRET_KEY}
      AWS_ENDPOINT: ${SAUVEGARDE_S3_ENDPOINT}
      AWS_S3_FORCE_PATH_STYLE: "true"
      AWS_REGION: ${SAUVEGARDE_S3_REGION}
      WALG_COMPRESSION_METHOD: lz4
    command:
      - "postgres"
      - "-c"
      - "archive_mode=on"
      - "-c"
      - "archive_command=wal-g wal-push %p"
      - "-c"
      - "wal_level=replica"
    volumes:
      - memoire_pgdata:/var/lib/postgresql/data
      - ./init-pgvector.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - default
      - proxy_net
    healthcheck:
```

(Le `healthcheck:` existant et tout ce qui suit dans le service restent inchangés — seule
la ligne `image:` est remplacée par `build:`, et `environment:`/`command:`/`volumes:` sont
complétés comme ci-dessus.)

Ajouter aussi `proxy_net` au bloc `networks:` en fin de fichier (absent aujourd'hui) :

```yaml
networks:
  default:
  proxy_net:
    external: true
    name: proxy_net
```

- [ ] **Step 3: Reconstruire et vérifier l'archivage**

Run: `cd /Users/garinat_t/Desktop/Workplace/briques/memoire && docker compose up -d --build memoire-db`
Expected: build réussi, `memoire-db` passe `healthy`.

Run: `docker exec workplace_memoire-db-1 wal-g wal-verify` (ou nom réel du conteneur, cf. `docker ps --filter name=memoire`)
Expected: pas d'erreur de configuration (connexion S3 acceptée) — au pire "no backups found" si aucun WAL n'a encore tourné, jamais une erreur d'authentification/endpoint.

- [ ] **Step 4: Preuve bout-en-bout — forcer un segment WAL et vérifier son arrivée sur S3**

Run:
```bash
docker exec workplace_memoire-db-1 psql -U memory -d memory -c "CREATE TABLE IF NOT EXISTS preuve_rpo (id serial, valeur text); INSERT INTO preuve_rpo (valeur) VALUES ('walg-ok'); SELECT pg_switch_wal();"
sleep 5
docker run --rm --network proxy_net -e MC_HOST_local="http://${SAUVEGARDE_S3_ACCESS_KEY}:${SAUVEGARDE_S3_SECRET_KEY}@minio:9000" minio/mc:RELEASE.2026-07-16T18-52-24Z ls local/workplace-sauvegardes/memoire-wal/
```
Expected: au moins un objet `wal_005/...` ou similaire listé, avec une date de modification
récente (moins d'une minute).

- [ ] **Step 5: Commit**

```bash
git add briques/memoire/Dockerfile.walg briques/memoire/docker-compose.yml
git commit -m "feat(memoire): archivage WAL continu Postgres→S3 via WAL-G"
```

---

### Task 5: Archivage WAL continu de `gateway` (Postgres) avec WAL-G

**Files:**
- Create: `briques/gateway/Dockerfile.walg`
- Modify: `briques/gateway/docker-compose.yml`

**Interfaces:**
- Consumes: variables `SAUVEGARDE_S3_*` (Task 1).
- Produces: chaque segment WAL de `db` (gateway) expédié vers `s3://workplace-sauvegardes/gateway-wal/`.

- [ ] **Step 1: Créer `briques/gateway/Dockerfile.walg`**

```dockerfile
# postgres:16.14-alpine (Alpine/musl) est incompatible avec le binaire WAL-G officiel
# (glibc). On bascule sur la variante Debian bookworm, même version majeure/mineure —
# cf. recherche du plan docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md.
FROM postgres:16.14-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL -o /tmp/wal-g.tar.gz \
       https://github.com/wal-g/wal-g/releases/download/v3.0.8/wal-g-pg-22.04-amd64.tar.gz \
    && tar -xzf /tmp/wal-g.tar.gz -C /tmp \
    && mv /tmp/wal-g-pg-22.04-amd64 /usr/local/bin/wal-g \
    && chmod +x /usr/local/bin/wal-g \
    && rm /tmp/wal-g.tar.gz \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Modifier `briques/gateway/docker-compose.yml`**

Remplacer `image: postgres:16.14-alpine` du service `db` par un build, et ajouter les
variables WAL-G + `archive_command` (même motif que Task 4) :

```yaml
  db:
    build:
      context: .
      dockerfile: Dockerfile.walg
    image: workplace/gateway-db-walg:0.1.0   # tag épinglé (pas de :latest flottant, cf. convention du parc)
    environment:
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: ${GATEWAY_DB_PASSWORD:-litellm}
      POSTGRES_DB: litellm
      WALG_S3_PREFIX: s3://${SAUVEGARDE_S3_BUCKET}/gateway-wal
      AWS_ACCESS_KEY_ID: ${SAUVEGARDE_S3_ACCESS_KEY}
      AWS_SECRET_ACCESS_KEY: ${SAUVEGARDE_S3_SECRET_KEY}
      AWS_ENDPOINT: ${SAUVEGARDE_S3_ENDPOINT}
      AWS_S3_FORCE_PATH_STYLE: "true"
      AWS_REGION: ${SAUVEGARDE_S3_REGION}
      WALG_COMPRESSION_METHOD: lz4
    command:
      - "postgres"
      - "-c"
      - "archive_mode=on"
      - "-c"
      - "archive_command=wal-g wal-push %p"
      - "-c"
      - "wal_level=replica"
    volumes:
      - gateway_db:/var/lib/postgresql/data
    networks:
      - default
      - proxy_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped
```

Ajouter `proxy_net` externe en fin de fichier (même bloc que Task 4, Step 2).

- [ ] **Step 3: Reconstruire et vérifier**

Run: `cd /Users/garinat_t/Desktop/Workplace/briques/gateway && docker compose up -d --build db`
Expected: build réussi, `db` passe `healthy` (`pg_isready`).

- [ ] **Step 4: Preuve bout-en-bout**

Run:
```bash
docker exec $(docker ps -qf "name=gateway-db-1") psql -U litellm -d litellm -c "CREATE TABLE IF NOT EXISTS preuve_rpo (id serial, valeur text); INSERT INTO preuve_rpo (valeur) VALUES ('walg-ok'); SELECT pg_switch_wal();"
sleep 5
docker run --rm --network proxy_net -e MC_HOST_local="http://${SAUVEGARDE_S3_ACCESS_KEY}:${SAUVEGARDE_S3_SECRET_KEY}@minio:9000" minio/mc:RELEASE.2026-07-16T18-52-24Z ls local/workplace-sauvegardes/gateway-wal/
```
Expected: au moins un objet listé, daté de moins d'une minute.

- [ ] **Step 5: Commit**

```bash
git add briques/gateway/Dockerfile.walg briques/gateway/docker-compose.yml
git commit -m "feat(gateway): archivage WAL continu Postgres→S3 via WAL-G"
```

---

### Task 6: Scripts de restauration + preuve de reprise complète

**Files:**
- Create: `outils/sauvegarde/restaurer_sqlite.sh`
- Create: `outils/sauvegarde/restaurer_postgres.sh`

**Interfaces:**
- Consumes: les répliques créées par les Tasks 2-5.
- Produces: deux scripts exécutables prouvant qu'on peut vraiment reconstruire une base à partir de la sauvegarde, sur une machine où le volume Docker d'origine n'existe pas — le seul test qui compte réellement pour une sauvegarde.

- [ ] **Step 1: Créer `outils/sauvegarde/restaurer_sqlite.sh`**

```bash
#!/usr/bin/env bash
# Restaure une base SQLite depuis sa réplique Litestream, dans un volume Docker neuf.
# Usage : restaurer_sqlite.sh <brique> <chemin_db_dans_le_volume> <volume_docker_cible>
# Exemple : restaurer_sqlite.sh donnees /data/donnees.db donnees_donnees_data
set -euo pipefail

BRIQUE="$1"; CHEMIN_DB="$2"; VOLUME_CIBLE="$3"

docker volume create "$VOLUME_CIBLE" >/dev/null

docker run --rm \
  --network proxy_net \
  --env-file "$(dirname "$0")/../../.env" \
  -e LITESTREAM_S3_PATH="$BRIQUE" \
  -v "$VOLUME_CIBLE:/data" \
  litestream/litestream:0.5.15 \
  restore -o "$CHEMIN_DB" \
  "s3://${SAUVEGARDE_S3_BUCKET}/${BRIQUE}?endpoint=${SAUVEGARDE_S3_ENDPOINT}&force-path-style=true&region=${SAUVEGARDE_S3_REGION}&access-key-id=${SAUVEGARDE_S3_ACCESS_KEY}&secret-access-key=${SAUVEGARDE_S3_SECRET_KEY}"

echo "Restauré dans le volume $VOLUME_CIBLE : $CHEMIN_DB"
```

- [ ] **Step 2: Créer `outils/sauvegarde/restaurer_postgres.sh`**

```bash
#!/usr/bin/env bash
# Restaure une base Postgres depuis ses WAL WAL-G, dans un volume Docker neuf.
# Usage : restaurer_postgres.sh <prefixe_s3> <volume_docker_cible> <image_walg>
# Exemple : restaurer_postgres.sh memoire-wal memoire_memoire_pgdata_restaure workplace/memoire-db-walg:0.1.0
set -euo pipefail

PREFIXE="$1"; VOLUME_CIBLE="$2"; IMAGE_WALG="$3"
source "$(dirname "$0")/../../.env"

docker volume create "$VOLUME_CIBLE" >/dev/null

docker run --rm \
  --network proxy_net \
  -e WALG_S3_PREFIX="s3://${SAUVEGARDE_S3_BUCKET}/${PREFIXE}" \
  -e AWS_ACCESS_KEY_ID="${SAUVEGARDE_S3_ACCESS_KEY}" \
  -e AWS_SECRET_ACCESS_KEY="${SAUVEGARDE_S3_SECRET_KEY}" \
  -e AWS_ENDPOINT="${SAUVEGARDE_S3_ENDPOINT}" \
  -e AWS_S3_FORCE_PATH_STYLE=true \
  -e AWS_REGION="${SAUVEGARDE_S3_REGION}" \
  -v "$VOLUME_CIBLE:/var/lib/postgresql/data" \
  --entrypoint wal-g \
  "$IMAGE_WALG" \
  backup-fetch /var/lib/postgresql/data LATEST

echo "Base restaurée (fichiers + WAL de base) dans $VOLUME_CIBLE."
echo "Prochaine étape manuelle : démarrer un conteneur Postgres pointé sur ce volume avec"
echo "restore_command='wal-g wal-fetch %f %p' pour rejouer les WAL jusqu'au dernier connu."
```

- [ ] **Step 3: Rendre les scripts exécutables**

Run: `chmod +x /Users/garinat_t/Desktop/Workplace/outils/sauvegarde/restaurer_sqlite.sh /Users/garinat_t/Desktop/Workplace/outils/sauvegarde/restaurer_postgres.sh`

- [ ] **Step 4: Preuve bout-en-bout réelle — perte simulée puis restauration de `donnees`**

Run:
```bash
cd /Users/garinat_t/Desktop/Workplace/briques/donnees
docker compose down -v   # simule la perte totale du volume (comme un disque HP mort)
cd /Users/garinat_t/Desktop/Workplace
./outils/sauvegarde/restaurer_sqlite.sh donnees /data/donnees.db donnees_donnees_data
docker run --rm -v donnees_donnees_data:/data python:3.12-slim python3 -c "
import sqlite3
c = sqlite3.connect('/data/donnees.db')
print(list(c.execute('SELECT valeur FROM preuve_rpo')))
"
```
Expected: la sortie contient `[('litestream-ok',)]` — la ligne écrite en Task 2 Step 4 est
bien revenue depuis S3, dans un volume qui n'existait plus.

Run: `cd /Users/garinat_t/Desktop/Workplace/briques/donnees && docker compose up -d`
Expected: `donnees` redémarre normalement sur le volume restauré.

- [ ] **Step 5: Commit**

```bash
git add outils/sauvegarde/restaurer_sqlite.sh outils/sauvegarde/restaurer_postgres.sh
git commit -m "feat(sauvegarde): scripts de restauration + preuve perte simulée/restauration"
```

---

## Limites connues de ce plan (documentées, pas résolues ici)

- **Cohérence inter-brique** : `memoire`, `donnees`, `gateway`, `agenda` sont restaurées
  indépendamment ; à la seconde près chacune, mais pas garanties parfaitement synchronisées
  entre elles au même instant exact (ex. l'agenda pourrait référencer un ID créé une seconde
  après le dernier WAL restauré côté mémoire). Acceptable pour l'usage actuel (cercle privé
  décrit avec l'utilisateur) — à revisiter si le multi-tenant devient réel (tiers payants).
- **Oria/Patroni** hors périmètre de ce plan (décision explicite de l'utilisateur : ces 4
  briques d'abord). Son `archive_command` actuel écrit en LOCAL
  (`/var/lib/postgresql/wal_archive`) — un futur plan devra le faire pointer vers S3 avec le
  même motif WAL-G que Task 4/5.
- **Sauvegarde complète périodique (base backup)** : ce plan ne programme pas encore
  `wal-g backup-push` sur un cron — l'archivage WAL continu suffit pour l'objectif RPO
  "quelques secondes", mais sans purge périodique des vieux WAL, le stockage S3 grossit sans
  limite. À traiter dans un plan de suivi (backup-push planifié + rétention `wal-g delete`).
- **GoBackup** garde son rôle pour les fichiers hors base (uploads, médias) — non traité ici,
  hors périmètre (bases de données uniquement).
