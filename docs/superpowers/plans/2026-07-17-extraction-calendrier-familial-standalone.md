# Extraction « Calendrier Familial » — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produire un dépôt Git autonome et auto-hébergeable (`calendrier-familial`) qui embarque la brique agenda de Workplace sans aucune modification de son code, lançable par `docker compose up`, plus un script de synchro côté Workplace.

**Architecture:** La brique agenda est déjà quasi-autonome (1 seul import externe : `shared.workplace_auth`). On construit un dépôt standalone où le code `backend/` est une **copie verbatim** et les dépendances externes (paquet vendored `agent_personnel_shared`, fichier `workplace_auth.py`) sont placées sous `vendor/` en **préservant les chemins d'import**. Le dépôt possède ses propres fichiers wrapper (Dockerfile/compose/entrypoint/README/LICENSE) ; un `export-standalone.sh` dans Workplace rafraîchit le code copié. Rien n'est publié sur GitHub sans confirmation.

**Tech Stack:** Docker + docker compose, Python 3.12 (image de base), FastAPI/SQLAlchemy/aiosqlite (agenda), Keycloak (profil multi optionnel), shell POSIX (entrypoint + script de synchro).

## Global Constraints

- **STANDALONE_DIR** = `/Users/garinat_t/Desktop/calendrier-familial` (dépôt Git indépendant, HORS du monorepo Workplace).
- **WORKPLACE_DIR** = `/Users/garinat_t/Desktop/Workplace/.claude/worktrees/s171-login-keycloak-coeur` (répertoire de travail courant ; source des copies).
- **Zéro modification du code `backend/`** : c'est la preuve d'autonomie. On ne patche jamais `backend/` dans le dépôt standalone — toute évolution passe par re-synchro depuis Workplace.
- Chemins d'import **préservés** : `from shared.workplace_auth import ...` et `import agent_personnel_shared` doivent fonctionner dans l'image standalone comme dans Workplace.
- **Licence Apache-2.0** ; nom produit « Calendrier Familial » ; dépôt `calendrier-familial`.
- **Auth par défaut** : `AUTH_ENABLED=false` (mono-user) ; multi-user = `docker compose --profile multi up`.
- **VAULT_SECRET** : jamais de secret par défaut en clair. L'`entrypoint.sh` en génère un aléatoire persisté dans `/data/.secret_vault` au 1er boot si ni `VAULT_SECRET` ni `AGENDA_ENCRYPTION_KEY` ne sont fournis.
- **Push/digest** désactivés par défaut (`CONNEXION_URL`/`MAIL_URL` vides → repli honnête déjà codé).
- **Publication GitHub gardée** : construite et prouvée en local ; création/push public seulement après confirmation explicite de l'utilisateur (Task 7, non auto-exécutée).
- Commits du dépôt standalone : `git -C "$STANDALONE_DIR" ...`. Commits Workplace : depuis WORKPLACE_DIR.
- Port de l'app : **8400** ; endpoints de preuve : `GET /health` (200), `GET /app` (200, page mono-user).

---

## File Structure

**Dépôt standalone (`$STANDALONE_DIR`) :**
- `backend/` — copie verbatim de `briques/agenda/backend/` (peuplée par le script, Task 2).
- `vendor/agent_personnel_shared/` — copie de `briques/agenda/shared/` (Task 2).
- `vendor/shared/{__init__.py,workplace_auth.py}` — le seul fichier externe + init minimal (Task 2).
- `Dockerfile`, `entrypoint.sh` — image + génération VAULT_SECRET (Task 3).
- `docker-compose.yml`, `keycloak/realm-calendrier.json` — modes défaut + multi (Task 4).
- `README.md` (Task 5), `LICENSE`, `NOTICE`, `.gitignore`, `.env.example` (Task 1).

**Workplace (`$WORKPLACE_DIR`) :**
- `scripts/export-standalone.sh` — synchro Workplace → standalone (Task 2).

---

## Task 1: Squelette du dépôt standalone (fichiers wrapper statiques)

**Files:**
- Create: `$STANDALONE_DIR/LICENSE`, `$STANDALONE_DIR/NOTICE`, `$STANDALONE_DIR/.gitignore`, `$STANDALONE_DIR/.env.example`

**Interfaces:**
- Produces: le dépôt Git standalone initialisé avec licence Apache-2.0 et `.env.example` (variables lues par `backend/config.py` : `VAULT_SECRET`, `AGENDA_ENCRYPTION_KEY`, `AUTH_ENABLED`, `KEYCLOAK_*`, `CONNEXION_URL`, `MAIL_URL`, `GOOGLE_*`).

- [ ] **Step 1: Initialiser le dépôt**

```bash
mkdir -p "$STANDALONE_DIR"
git -C "$STANDALONE_DIR" init -q
```

- [ ] **Step 2: Licence Apache-2.0**

Écrire le texte **intégral** de la licence Apache-2.0 dans `$STANDALONE_DIR/LICENSE` (texte officiel, https://www.apache.org/licenses/LICENSE-2.0.txt — copier tel quel, ~11 KB). Puis `$STANDALONE_DIR/NOTICE` :

```
Calendrier Familial
Copyright 2026 Toussaint Garinat

This product includes software developed as part of the Workplace project.
Licensed under the Apache License, Version 2.0.
```

- [ ] **Step 3: `.gitignore`**

`$STANDALONE_DIR/.gitignore` :

```gitignore
__pycache__/
*.pyc
.pytest_cache/
*.db
*.db-journal
/data/
.env
```

- [ ] **Step 4: `.env.example`**

`$STANDALONE_DIR/.env.example` :

```dotenv
# ── Calendrier Familial — configuration ────────────────────────────────────
# Copiez ce fichier en .env : `cp .env.example .env`
# Tout est optionnel : `docker compose up` fonctionne sans .env (mono-utilisateur,
# secret de chiffrement auto-généré au 1er démarrage).

# Chiffrement au repos (AES-GCM). Laissez vide pour qu'un secret soit généré et
# persisté automatiquement dans le volume au 1er lancement. Pour le contrôler
# vous-même, posez une valeur forte et NE LA PERDEZ PAS (sinon données illisibles).
# VAULT_SECRET=

# Partage familial (multi-utilisateur) — activé par `docker compose --profile multi up`.
# En dehors de ce profil, l'app tourne en mono-utilisateur (aucun login).
# AUTH_ENABLED=false

# Notifications optionnelles (laisser vide = désactivé, repli honnête) :
# CONNEXION_URL=   # pont push web/messagerie
# MAIL_URL=        # brique mail pour le digest email

# Import Google Agenda (optionnel) :
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
```

- [ ] **Step 5: Vérifier**

Run: `ls "$STANDALONE_DIR" && head -1 "$STANDALONE_DIR/LICENSE" && git -C "$STANDALONE_DIR" status --short | head`
Expected: LICENSE/NOTICE/.gitignore/.env.example présents ; première ligne de LICENSE = `                                 Apache License` ; fichiers non suivis listés.

- [ ] **Step 6: Commit (dépôt standalone)**

```bash
git -C "$STANDALONE_DIR" add -A
git -C "$STANDALONE_DIR" commit -q -m "chore: squelette dépôt (licence Apache-2.0, .env.example)"
```

---

## Task 2: Script `export-standalone.sh` + peuplement du code

**Files:**
- Create: `$WORKPLACE_DIR/scripts/export-standalone.sh`
- Produces (dans STANDALONE): `backend/`, `vendor/agent_personnel_shared/`, `vendor/shared/{__init__.py,workplace_auth.py}`

**Interfaces:**
- Consumes: l'arborescence Workplace `briques/agenda/backend`, `briques/agenda/shared`, `shared/workplace_auth.py`.
- Produces: un dépôt standalone dont `backend/` est une copie verbatim (import `shared.workplace_auth` et `agent_personnel_shared` résolubles une fois l'image construite en Task 3).

- [ ] **Step 1: Écrire le script**

`$WORKPLACE_DIR/scripts/export-standalone.sh` :

```bash
#!/usr/bin/env bash
# Synchronise le code de la brique agenda vers le dépôt standalone Calendrier Familial.
# La brique Workplace reste la SOURCE DE VÉRITÉ ; ce script rafraîchit uniquement le
# code copié (backend/ + vendor/), jamais les fichiers wrapper du dépôt standalone
# (Dockerfile, docker-compose.yml, entrypoint.sh, README.md, LICENSE, keycloak/).
set -euo pipefail

DEST="${1:?usage: export-standalone.sh <chemin-du-depot-standalone>}"
SRC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # racine Workplace

EXCLUDES=(--exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache'
          --exclude='*.db' --exclude='*.db-journal' --exclude='data')

mkdir -p "$DEST/backend" "$DEST/vendor/agent_personnel_shared" "$DEST/vendor/shared"

# 1) backend = copie verbatim
rsync -a --delete "${EXCLUDES[@]}" "$SRC_ROOT/briques/agenda/backend/" "$DEST/backend/"

# 2) paquet vendored agent_personnel_shared
rsync -a --delete "${EXCLUDES[@]}" "$SRC_ROOT/briques/agenda/shared/" "$DEST/vendor/agent_personnel_shared/"

# 3) le seul fichier externe utilisé + un __init__ minimal (pas de llm_client)
cp "$SRC_ROOT/shared/workplace_auth.py" "$DEST/vendor/shared/workplace_auth.py"
cat > "$DEST/vendor/shared/__init__.py" <<'PY'
"""Sous-ensemble vendoré de la lib partagée Workplace (workplace_auth uniquement)."""
PY

echo "Synchro OK -> $DEST (backend/ + vendor/)"
```

- [ ] **Step 2: Rendre exécutable et lancer**

```bash
chmod +x "$WORKPLACE_DIR/scripts/export-standalone.sh"
"$WORKPLACE_DIR/scripts/export-standalone.sh" "$STANDALONE_DIR"
```

Expected: `Synchro OK -> …`

- [ ] **Step 3: Vérifier le peuplement**

Run:
```bash
test -f "$STANDALONE_DIR/backend/main.py" && echo backend-ok
test -f "$STANDALONE_DIR/backend/crypto.py" && echo crypto-ok
test -f "$STANDALONE_DIR/vendor/agent_personnel_shared/pyproject.toml" && echo vendor-pkg-ok
test -f "$STANDALONE_DIR/vendor/shared/workplace_auth.py" && echo workplace-auth-ok
find "$STANDALONE_DIR/backend" -name '__pycache__' -o -name '*.db' | head
```
Expected: les 4 `*-ok` ; aucun `__pycache__`/`*.db` listé (dernière commande vide).

- [ ] **Step 4: Commit script (Workplace) + code (standalone)**

```bash
git -C "$WORKPLACE_DIR" add scripts/export-standalone.sh
git -C "$WORKPLACE_DIR" commit -q -m "feat: script export-standalone.sh (synchro agenda -> Calendrier Familial)"
git -C "$STANDALONE_DIR" add -A
git -C "$STANDALONE_DIR" commit -q -m "feat: code agenda (backend verbatim + vendor)"
```

---

## Task 3: Dockerfile + entrypoint (image standalone)

**Files:**
- Create: `$STANDALONE_DIR/Dockerfile`, `$STANDALONE_DIR/entrypoint.sh`

**Interfaces:**
- Consumes: `backend/requirements.txt`, `vendor/agent_personnel_shared/`, `vendor/shared/` (Task 2).
- Produces: image `calendrier-familial` exposant 8400, entrypoint garantissant un `VAULT_SECRET`.

- [ ] **Step 1: `entrypoint.sh`**

`$STANDALONE_DIR/entrypoint.sh` :

```sh
#!/bin/sh
# Génère et persiste un VAULT_SECRET au 1er démarrage si l'utilisateur n'en fournit pas,
# afin que le chiffrement au repos fonctionne sans exiger de configuration manuelle et
# sans livrer de secret par défaut en clair.
set -e
SECRET_FILE=/data/.secret_vault
if [ -z "${VAULT_SECRET:-}" ] && [ -z "${AGENDA_ENCRYPTION_KEY:-}" ]; then
  if [ ! -f "$SECRET_FILE" ]; then
    mkdir -p /data
    head -c 32 /dev/urandom | base64 | tr -d '\n' > "$SECRET_FILE"
    echo "[entrypoint] VAULT_SECRET généré et persisté ($SECRET_FILE)"
  fi
  VAULT_SECRET="$(cat "$SECRET_FILE")"
  export VAULT_SECRET
fi
exec "$@"
```

- [ ] **Step 2: `Dockerfile`**

`$STANDALONE_DIR/Dockerfile` (repris de la brique Workplace, chemins adaptés au contexte standalone) :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir setuptools

# Paquet vendoré (Redis, helpers FastAPI, S2S, jobs) — importable en `agent_personnel_shared`.
COPY vendor/agent_personnel_shared /opt/agent_personnel_shared
RUN pip install --no-cache-dir -e /opt/agent_personnel_shared

# Lib partagée minimale — rend `shared.workplace_auth` importable.
COPY vendor/shared/ /app/shared/

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN mkdir -p /data/calendar/attachments && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8400

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8400/health >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400"]
```

- [ ] **Step 3: Construire l'image**

Run: `docker build -t calendrier-familial "$STANDALONE_DIR"`
Expected: build réussi jusqu'à `naming to docker.io/library/calendrier-familial` (pas d'erreur `pip`/`COPY`).

- [ ] **Step 4: Commit (standalone)**

```bash
git -C "$STANDALONE_DIR" add Dockerfile entrypoint.sh
git -C "$STANDALONE_DIR" commit -q -m "feat: Dockerfile + entrypoint (VAULT_SECRET auto-généré au 1er boot)"
```

---

## Task 4: docker-compose (défaut + profil multi) + realm Keycloak

**Files:**
- Create: `$STANDALONE_DIR/docker-compose.yml`, `$STANDALONE_DIR/keycloak/realm-calendrier.json`

**Interfaces:**
- Consumes: image construite (Task 3), variables lues par `backend/config.py`.
- Produces: `docker compose up` (mono-user) et `docker compose --profile multi up` (Keycloak realm `calendrier`, client `calendar-app`).

- [ ] **Step 1: `docker-compose.yml`**

`$STANDALONE_DIR/docker-compose.yml` :

```yaml
services:
  agenda:
    build: .
    image: calendrier-familial
    ports:
      - "8400:8400"
    environment:
      - DATABASE_URL=
      - REDIS_URL=
      - CORS_ORIGINS=http://localhost:8400
      - ATTACHMENTS_DIR=/data/calendar/attachments
      - AUTH_ENABLED=${AUTH_ENABLED:-false}
      - KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8080}
      - KEYCLOAK_PUBLIC_URL=${KEYCLOAK_PUBLIC_URL:-http://localhost:8080}
      - KEYCLOAK_REALM=${KEYCLOAK_REALM:-calendrier}
      - KEYCLOAK_CLIENT_ID=${KEYCLOAK_CLIENT_ID:-calendar-app}
      - KEYCLOAK_AUDIENCE=${KEYCLOAK_AUDIENCE:-calendar-app}
      - VAULT_SECRET=${VAULT_SECRET:-}
      - AGENDA_ENCRYPTION_KEY=${AGENDA_ENCRYPTION_KEY:-}
      - CONNEXION_URL=${CONNEXION_URL:-}
      - MAIL_URL=${MAIL_URL:-}
    volumes:
      - calendrier_data:/data

  # Partage familial — démarré uniquement avec `--profile multi`.
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    profiles: ["multi"]
    command: ["start-dev", "--import-realm", "--http-enabled=true", "--hostname-strict=false"]
    environment:
      - KC_BOOTSTRAP_ADMIN_USERNAME=admin
      - KC_BOOTSTRAP_ADMIN_PASSWORD=admin
    ports:
      - "8080:8080"
    volumes:
      - ./keycloak/realm-calendrier.json:/opt/keycloak/data/import/realm-calendrier.json:ro

volumes:
  calendrier_data:
```

Note : en profil multi, l'utilisateur pose `AUTH_ENABLED=true` dans son `.env` (documenté README) ; l'app lit alors `KEYCLOAK_*` ci-dessus.

- [ ] **Step 2: `keycloak/realm-calendrier.json`**

`$STANDALONE_DIR/keycloak/realm-calendrier.json` (realm minimal importable, inscription ouverte, client public `calendar-app` PKCE) :

```json
{
  "realm": "calendrier",
  "enabled": true,
  "registrationAllowed": true,
  "resetPasswordAllowed": true,
  "loginWithEmailAllowed": true,
  "sslRequired": "none",
  "clients": [
    {
      "clientId": "calendar-app",
      "enabled": true,
      "publicClient": true,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "redirectUris": ["http://localhost:8400/*"],
      "webOrigins": ["http://localhost:8400"],
      "attributes": { "pkce.code.challenge.method": "S256" }
    }
  ]
}
```

- [ ] **Step 3: Valider la config compose (défaut + multi)**

Run:
```bash
docker compose -f "$STANDALONE_DIR/docker-compose.yml" config >/dev/null && echo config-defaut-ok
docker compose -f "$STANDALONE_DIR/docker-compose.yml" --profile multi config | grep -q keycloak && echo profil-multi-inclut-keycloak
```
Expected: `config-defaut-ok` puis `profil-multi-inclut-keycloak`.

- [ ] **Step 4: Commit (standalone)**

```bash
git -C "$STANDALONE_DIR" add docker-compose.yml keycloak/realm-calendrier.json
git -C "$STANDALONE_DIR" commit -q -m "feat: docker-compose (mono-user défaut + profil multi Keycloak)"
```

---

## Task 5: README

**Files:**
- Create: `$STANDALONE_DIR/README.md`

- [ ] **Step 1: Écrire le README**

`$STANDALONE_DIR/README.md` :

```markdown
# Calendrier Familial

Agenda familial **souverain, auto-hébergé et gratuit** (Apache-2.0). Vos données
restent chez vous et sont **chiffrées au repos** (AES-GCM) — illisibles même dans un
dump de base. Alternative auto-hébergeable à TimeTree / Cozi.

## Démarrage rapide (mono-utilisateur)

```bash
git clone <url> calendrier-familial && cd calendrier-familial
docker compose up -d
```
Ouvrez **http://localhost:8400/app**. C'est tout — aucun compte requis, un secret de
chiffrement est généré et persisté automatiquement au premier lancement.

## Partage familial (multi-utilisateur)

```bash
echo "AUTH_ENABLED=true" >> .env
docker compose --profile multi up -d
```
Un serveur d'identité (Keycloak) démarre sur http://localhost:8080. Chaque membre
crée son compte depuis la page de connexion, puis le propriétaire d'un calendrier
partage un **lien d'invitation** (rôles consultation / édition).

## Fonctionnalités

Calendrier (mois/semaine), événements récurrents (RRULE), étiquettes, invitations,
**listes de courses** partagées, **sondages** de disponibilité, **présence** (carte),
cartes de fidélité, **PWA** installable, abonnement **ICS/webcal**, chiffrement au repos.

## Intégrations optionnelles

- **Notifications push / digest email** : renseignez `CONNEXION_URL` / `MAIL_URL` dans
  `.env` (voir `.env.example`). Sans ça, l'app fonctionne, ces canaux sont simplement
  inactifs.
- **Import Google Agenda** : `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

## Sauvegarde

Toutes les données (base, secret de chiffrement, pièces jointes) vivent dans le volume
Docker `calendrier_data`. Sauvegardez-le régulièrement. **Ne perdez pas** votre
`VAULT_SECRET` (auto-généré dans `/data/.secret_vault`) : sans lui, les données chiffrées
sont irrécupérables.

## Licence

Apache-2.0.
```

- [ ] **Step 2: Vérifier**

Run: `grep -q 'http://localhost:8400/app' "$STANDALONE_DIR/README.md" && grep -q 'profile multi' "$STANDALONE_DIR/README.md" && echo readme-ok`
Expected: `readme-ok`

- [ ] **Step 3: Commit (standalone)**

```bash
git -C "$STANDALONE_DIR" add README.md
git -C "$STANDALONE_DIR" commit -q -m "docs: README (démarrage rapide, multi-user, chiffrement, sauvegarde)"
```

---

## Task 6: Vérification bout-en-bout (build + up + tests)

**Files:** aucun fichier créé — tâche de preuve.

- [ ] **Step 1: Démarrer en mode défaut (mono-user)**

Run:
```bash
docker compose -f "$STANDALONE_DIR/docker-compose.yml" up -d --build
sleep 8
curl -s -o /dev/null -w "health=%{http_code}\n" http://localhost:8400/health
curl -s -o /dev/null -w "app=%{http_code}\n" http://localhost:8400/app
docker compose -f "$STANDALONE_DIR/docker-compose.yml" logs --tail 15 agenda | grep -iE 'ready|secret|started|error'
```
Expected: `health=200`, `app=200`, un log `[entrypoint] VAULT_SECRET généré…` + `Calendar service started`, aucune trace `error`/exception de déchiffrement.

- [ ] **Step 2: Prouver l'écriture/lecture chiffrée end-to-end (mono-user)**

Run:
```bash
docker compose -f "$STANDALONE_DIR/docker-compose.yml" exec -T agenda python -c "
import asyncio
from db import AsyncSessionLocal, init_db
from models.orm import Calendar, Event
from sqlalchemy import select, text
import datetime as dt
async def m():
    await init_db()
    async with AsyncSessionLocal() as s:
        s.add(Calendar(id='c1', user_id='perso', name='Fam'))
        s.add(Event(id='e1', calendar_id='c1', title='Test chiffré',
                    start_at=dt.datetime(2026,8,1,9), end_at=dt.datetime(2026,8,1,10),
                    created_by='perso'))
        await s.commit()
        ev = (await s.execute(select(Event).where(Event.id=='e1'))).scalar_one()
        raw = (await s.execute(text(\"select title from events where id='e1'\"))).scalar()
        print('clair=', repr(ev.title), '| brut_chiffré=', repr(raw[:16]))
        assert ev.title == 'Test chiffré' and 'Test' not in raw
        print('OK chiffrement transparent')
asyncio.run(m())
"
```
Expected: `clair= 'Test chiffré' | brut_chiffré= '...'` puis `OK chiffrement transparent`.

- [ ] **Step 3: Exécuter la suite de tests de l'agenda dans le contexte standalone**

Run:
```bash
docker compose -f "$STANDALONE_DIR/docker-compose.yml" run --rm --user root agenda \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests -q" 2>&1 | tail -6
```
Expected: `~341 passed` (1 skip possible), 0 failed — même code que Workplace, prouve l'autonomie des imports (`shared.workplace_auth`, `agent_personnel_shared`) dans l'image standalone.

- [ ] **Step 4: Smoke du profil multi (Keycloak)**

Run:
```bash
docker compose -f "$STANDALONE_DIR/docker-compose.yml" --profile multi up -d keycloak
sleep 25
curl -s -o /dev/null -w "kc_realm=%{http_code}\n" http://localhost:8080/realms/calendrier
docker compose -f "$STANDALONE_DIR/docker-compose.yml" --profile multi down
```
Expected: `kc_realm=200` (realm `calendrier` importé). (Si Keycloak met plus longtemps à démarrer, réessayer le curl ; le healthcheck n'est pas requis pour cette preuve.)

- [ ] **Step 5: Arrêter et consigner**

Run:
```bash
docker compose -f "$STANDALONE_DIR/docker-compose.yml" down
echo "Vérif OK : build + up mono-user + chiffrement + suite tests + realm multi"
```

- [ ] **Step 6: Commit (standalone) — état vérifié**

```bash
git -C "$STANDALONE_DIR" commit -q --allow-empty -m "test: build + up mono-user + suite agenda + realm multi vérifiés en local"
```

---

## Task 7: Publication GitHub — GARDÉE (confirmation utilisateur requise)

**NE PAS exécuter sans confirmation explicite de l'utilisateur** (action externe irréversible : rend le code public). Cette tâche documente la marche à suivre ; l'implémenteur s'ARRÊTE ici et demande confirmation (nom, visibilité, licence) au contrôleur/utilisateur.

- [ ] **Step 1: (Sur confirmation) créer le dépôt public et pousser**

```bash
gh repo create calendrier-familial --public \
  --description "Agenda familial souverain, auto-hébergé, chiffré au repos (Apache-2.0)" \
  --source "$STANDALONE_DIR" --remote origin --push
```
Expected: dépôt créé et branche poussée. Sinon (pas de confirmation) : laisser le dépôt local tel quel, ne rien publier.

---

## Self-Review (effectuée)

- **Couverture spec** : §1 structure → Tasks 1-5 ; §2 Dockerfile → Task 3 ; §3 compose+chiffrement/entrypoint → Tasks 3-4 ; §4 script synchro → Task 2 ; §5 README → Task 5 ; §6 vérification → Task 6 ; §7 publication gardée → Task 7 ; contrainte « zéro modif backend » → Task 2 (copie verbatim) + preuve Task 6 step 3.
- **Placeholders** : aucun — contenus de fichiers complets. Seule exception assumée : le texte intégral Apache-2.0 (Task 1 step 2) référencé par URL officielle (trop long à inliner, contenu standard invariant).
- **Cohérence** : port 8400, image `calendrier-familial`, realm `calendrier`, client `calendar-app`, chemins `vendor/agent_personnel_shared` + `vendor/shared/` cohérents entre Dockerfile (Task 3), script (Task 2) et compose (Task 4). Variables d'env alignées avec `backend/config.py`.
- **Point de vigilance** : la suite de tests (Task 6 step 3) installe `requirements-dev.txt` en root dans un conteneur jetable (les tests utilisent `create_all`, pas la migration) ; si `respx`/`pytest-asyncio` manquent d'un pin, c'est un souci de `requirements-dev.txt` amont (identique à Workplace), pas du standalone.
```
