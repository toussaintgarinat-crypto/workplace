# S125 — Bascule sur le HP & preuves LIVE groupées

> **But.** Cette machine de dev sature en disque dès qu'on build les grosses images
> Docker (`ENOSPC`). On a donc adopté le régime **« coder + tester + pousser ici,
> prouver LIVE en Docker là-bas »** : tout le code S114→S121 est sur GitHub
> (branche `refactor/s114-routes-coeur`), prouvé par tests natifs + comparaison de
> baseline. Ce document est le **runbook** pour rejouer les preuves LIVE en Docker sur
> une machine costaude (Proxmox HP 800 G4 i7-8700) **depuis GitHub**.

## 0. Ce qui voyage — et ce qui ne voyage pas

| Catégorie | Sur GitHub ? | Comment l'obtenir sur le HP |
|---|---|---|
| Code (Cœur + briques + `shared/`) | ✅ | `git clone` |
| `docker-compose.yml` + `Dockerfile` | ✅ | `git clone` |
| Gabarits `.env.example` | ✅ | `git clone` |
| Realms Keycloak (`*-realm.json`) | ✅ | `git clone` |
| **`.env` (secrets réels)** | ❌ (gitignorés, exprès) | **Copier** depuis cette machine (clé USB / `scp`) OU remplir les gabarits |
| Volumes Docker (données existantes) | ❌ | Optionnel : seulement pour la preuve « migration sur volume existant » |
| `oria-stack/shared/` | ❌ (hors périmètre) | Non requis pour S114→S121 |

### Les `.env` à fournir
- **Avec gabarit** (remplir sur le HP) : `.env` (racine), `briques/agenda/.env`,
  `briques/gateway/.env`, `briques/forge/.env` *(nouveau gabarit S125)*,
  `oria-stack/infra/keycloak/.env` *(nouveau gabarit S125)*,
  `briques/world-engine/.env` *(optionnel, second tenant `API_KEYS` — voir
  mesure de charge Sprint E ; sans lui `world-engine` reste utilisable avec
  un seul tenant, `WORLD_ENGINE_KEY` du `.env` racine)*.
- **Sans gabarit** (copier le fichier réel) : `briques/forge/forge/.env`,
  `briques/agenda/backend/.env`, `briques/memoire/.env`. Ils contiennent des secrets
  qui n'ont pas d'équivalent régénérable.

> Le **`.env` racine** est la clé maîtresse partagée (`GATEWAY_API_KEY`,
> `FORGE_SERVICE_SECRET`, `VAULT_SECRET`, `CALENDAR_SERVICE_TOKEN`…). forge & gateway le
> chargent via `env_file: ../../.env`. **Sans lui, rien ne s'authentifie.**

## 1. Cloner

```bash
git clone -b refactor/s114-routes-coeur \
  https://github.com/toussaintgarinat-crypto/workplace.git
cd workplace
```

## 2. Poser les secrets

```bash
cp .env.example .env                                   # puis remplir
cp briques/gateway/.env.example briques/gateway/.env    # clé OpenRouter…
cp briques/forge/.env.example briques/forge/.env        # FORGE_DB_PASSWORD, FORGE_ENCRYPTION_KEY…
cp briques/agenda/.env.example briques/agenda/.env       # AGENDA_VAULT_SECRET…
cp oria-stack/infra/keycloak/.env.example oria-stack/infra/keycloak/.env
cp briques/world-engine/.env.example briques/world-engine/.env  # optionnel, 2e tenant
# Puis copier les .env SANS gabarit depuis la machine de dev :
#   briques/forge/forge/.env  briques/agenda/backend/.env  briques/memoire/.env
```

## 3. Préflight

```bash
bash scripts/preflight_hp.sh
```
Vérifie : Docker up, disque ≥ 20 Go libres, présence des `.env` requis, ports libres.

## 4. Vérifier l'intégrité du clone (tests natifs, sans Docker)

Rapide et sans coût disque — confirme que le clone est intègre **avant** de builder :
```bash
make smoke                                   # 185 passed / 6 skipped attendus
( cd briques/donnees && python3 -m pytest -q )   # 6 passed (test_multitenant)
( cd core && VAULT_SECRET=test GATEWAY_KEY=test python3 -m pytest test_contexte_tenant.py -q )  # 9 passed
```

## 5. Démarrer le stack

> ### ⚠️ Prérequis Linux (Docker Engine) — PROUVÉ LIVE 2026-06-29
> Deux différences vs macOS (Docker Desktop) à régler **avant** de builder, sinon le Cœur
> ne joint aucune brique :
> 1. **Réseau externe `proxy_net`** (référencé par gateway/agenda/core, `external: true`) :
>    ```bash
>    docker network create proxy_net   # idempotent : ignore l'erreur s'il existe déjà
>    ```
> 2. **`host.docker.internal`** n'existe pas nativement sur Linux : les briques
>    *consommatrices* (qui appellent les autres via `host.docker.internal:PORT`) ont besoin
>    du mapping `host-gateway`. Sans toucher les composes versionnés, poser un
>    `docker-compose.override.yml` (fusionné automatiquement) dans chaque brique concernée —
>    **core, audit, generateur, agenda, forge** (et **donnees** seulement en Niveau B) :
>    ```yaml
>    # briques/<nom>/docker-compose.override.yml  (core : à la racine du dossier core/)
>    services:
>      <service>:        # core | audit | generateur | agenda ; forge: forge + forge-adapter
>        extra_hosts:
>          - "host.docker.internal:host-gateway"
>    ```
>    (`studio` a déjà ce mapping en dur — précédent dans le repo.)

Ordre : **gateway → (keycloak si Niveau B) → briques socle → core**. Chaque brique :
```bash
( cd briques/<nom> && docker compose up -d --build )
```
> ⚠️ Toujours `--build` au premier lancement après un clone, et après chaque `git pull`
> (sinon images périmées — piège connu du launcher).

Minimal pour prouver S114→S121 (Niveau A) : `gateway`, `donnees`, `agenda`, `forge`,
`ingestion`, `audit`, `generateur`, puis `core`. (Sur macOS : `./Lancer\ Workplace.command`
monte tout le stack ; sur Linux/Proxmox, faire les `docker compose up -d --build` à la main.)

**Observabilité (S225)** — après `core`, puisqu'elle scrute son `/metrics` :
```bash
( cd outils/observabilite && docker compose up -d )
```
> ⚠️ Exige `GRAFANA_PASSWORD` dans le `.env` racine : sans lui Grafana **refuse de
> démarrer**, volontairement (pas de défaut « admin/admin » sur une UI joignable depuis le
> mesh). Prometheus sur `:9090`, Grafana sur `:3001` (3000 est déjà pris dans le parc).
> Le tableau « Workplace — parc » et les alertes sont provisionnés depuis le dépôt.
>
> Vérification : `curl -s localhost:5100/metrics | head` doit sortir des lignes
> `workplace_*`, et `localhost:9090/targets` doit montrer la cible `coeur` en `UP`.

---

# 6. Preuves LIVE — Niveau A (sans Keycloak, `AUTH_ENABLED` off)

Le gros des preuves. Aucun Keycloak requis. Remplace `localhost` par l'IP du HP au besoin.

### S114 — découpage des routes (0 régression)
```bash
curl -s localhost:5100/openapi.json | python3 -c \
  "import sys,json; print('routes:', len(json.load(sys.stdin)['paths']))"
curl -s localhost:5100/health        # 200
curl -s localhost:5100/sante-globale # agrège la santé des briques
```
> Le nombre de routes **dépend des briques découvertes** (le Cœur monte des routes-proxy
> dynamiques par manifest). Stack complet ≈ 93 routes ; stack minimal Niveau A = 74 paths /
> 89 opérations (prouvé sur le HP). L'invariant S114 = l'app boote, routes éclatées en
> `routers/`, `/health` 200, zéro régression — pas un compteur figé.

### S116 — santé des briques
```bash
for p in 4001:health 5500:sante 8400:health 5700:sante; do
  port=${p%%:*}; route=${p##*:}; echo -n "$port/$route -> "
  curl -s -o /dev/null -w '%{http_code}\n' "localhost:$port/$route"
done
```

### S118/S120 — `shared/` importable DANS les conteneurs
```bash
( cd briques/donnees && docker compose exec donnees python3 -c \
  "import shared.workplace_auth as w; print('shared OK', bool(w.verify_token_sync))" )
( cd briques/generateur && docker compose exec generateur python3 -c \
  "import shared.llm_client as c; print('llm_client OK', bool(c.appeler_json))" )
```

### S118 — vrai appel LLM via la Gateway (bout-en-bout)
`appeler_json` est **async** et exige `system_prompt` (signature :
`appeler_json(user, *, system_prompt, temperature=0.1, model=None) -> dict`) :
```bash
( cd briques/audit && docker compose exec -T audit python3 -c \
  "import asyncio, shared.llm_client as c; \
   print(asyncio.run(c.appeler_json('Donne le nombre 42.', \
   system_prompt='Réponds STRICTEMENT en JSON: {\"produit\": <entier>}')))" )
# Attendu : {'produit': 42}
```

### S119 — contrat Audit→Générateur figé (schéma partagé)
```bash
# Importer un audit témoin puis vérifier que /audits/{id} est sérialisé par le response_model
curl -s localhost:5300/audits/<id> | python3 -m json.tool | head
```

### S121 — isolation par organisation de `donnees` (en-tête `X-Org-ID`)
```bash
B=localhost:5500/apps/app1/entites/clients/enregistrements
curl -s -X POST $B -H 'X-Org-ID: orgA' -H 'content-type: application/json' -d '{"nom":"Alice"}'
curl -s $B -H 'X-Org-ID: orgB'   # => []   (orgB ne voit rien)
curl -s $B -H 'X-Org-ID: orgA'   # => [{"nom":"Alice",...}]
curl -s $B                       # => []   (tenant « defaut », distinct)
```

### S121 — colonne `org_id` présente + migration appliquée
```bash
( cd briques/donnees && docker compose exec donnees python3 -c \
  "import sqlite3; print([r[1] for r in sqlite3.connect('/data/donnees.db').execute('PRAGMA table_info(enregistrements)')])" )
# Attendu : [...,'org_id',...]
```
> **Preuve « migration sur volume existant »** : démarrer d'abord une image
> **pré-S121** (checkout `e84ba85`, build, créer une ligne), puis `git checkout
> refactor/s114-routes-coeur`, `docker compose up -d --build`, et rejouer la requête
> ci-dessus : la colonne apparaît, l'ancienne ligne est lisible en tenant `defaut`.

### S121 — propagation `X-User-Id` vers agenda (par utilisateur)
```bash
# Un même tour Cœur portant X-User-Id crée/lit le calendrier de CET utilisateur.
curl -s localhost:5100/agenda/evenements -H 'X-User-Id: alice'   # calendrier d'alice
curl -s localhost:5100/agenda/evenements -H 'X-User-Id: bob'     # calendrier de bob (distinct)
```

---

# 7. Preuves LIVE — Niveau B (avec Keycloak, `AUTH_ENABLED` on)

Pour les preuves qui exigent une **vraie identité JWT**. Plus lourd.

### Démarrer Keycloak (importe les realms automatiquement)
```bash
( cd oria-stack/infra/keycloak && docker compose up -d )
# Console : http://<HP>:8080/admin  (KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD)
```

### Activer l'auth sur `donnees` (la preuve JWT)
Le compose `donnees` ne lit pas de `.env` : poser un `docker-compose.override.yml` (qui
ajoute aussi `extra_hosts` sur Linux pour joindre le JWKS Keycloak), puis recréer :
```yaml
# briques/donnees/docker-compose.override.yml
services:
  donnees:
    environment:
      - AUTH_ENABLED=true
      - KEYCLOAK_URL=http://host.docker.internal:8080   # Linux : via host-gateway
      - KEYCLOAK_REALM=forge
      # - KEYCLOAK_AUDIENCE=   # vide ⇒ verify_aud off (le realm suffit à isoler)
    extra_hosts:
      - "host.docker.internal:host-gateway"
```
```bash
( cd briques/donnees && docker compose up -d )
# Sans jeton → 401 (et non 500) :
curl -s -o /dev/null -w '%{http_code}\n' localhost:5500/apps/app1/entites/clients/enregistrements
```
> NB : `shared/workplace_auth` appelle `jwt.decode` **sans `issuer=`** → l'issuer n'est PAS
> vérifié (seule la signature RS256 via JWKS compte). Donc peu importe le host par lequel le
> jeton est émis ; pas de piège « issuer host mismatch ».

### Obtenir des jetons (realm `forge` sans utilisateurs : via les service-accounts)
Le realm `forge` n'a pas d'utilisateurs ni de mapper `org_id` (le tenant retombe alors sur
le claim `sub`). Frapper un jeton depuis un service-account (secret récupéré par l'API admin) :
```bash
KC=http://localhost:8080
ADMIN_PW=$(grep KEYCLOAK_ADMIN_PASSWORD oria-stack/infra/keycloak/.env | cut -d= -f2)
ADMIN=$(curl -s $KC/realms/master/protocol/openid-connect/token \
  -d client_id=admin-cli -d username=admin -d "password=$ADMIN_PW" -d grant_type=password \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# secret du service-account puis jeton client_credentials :
CID=$(curl -s "$KC/admin/realms/forge/clients?clientId=forge-service" -H "Authorization: Bearer $ADMIN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
SECRET=$(curl -s "$KC/admin/realms/forge/clients/$CID/client-secret" -H "Authorization: Bearer $ADMIN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['value'])")
TOKEN=$(curl -s "$KC/realms/forge/protocol/openid-connect/token" \
  -d client_id=forge-service -d "client_secret=$SECRET" -d grant_type=client_credentials \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# Avec jeton valide → 200 ; jeton trafiqué (${TOKEN}X) → 401.
curl -s -o /dev/null -w '%{http_code}\n' localhost:5500/apps/app1/entites/clients/enregistrements -H "Authorization: Bearer $TOKEN"
```
Pour l'isolation par claim (S121), répéter avec un 2e service-account (`oria-service`) :
`sub` distinct ⇒ chacun ne voit que ses données, **sans** `X-Org-ID`.

### S120 — validation JWT Keycloak réelle
```bash
# Obtenir un jeton (client password ou service) depuis Keycloak, puis :
TOKEN=...   # access_token d'un user de l'org A
curl -s localhost:5500/apps/app1/entites/clients/enregistrements -H "Authorization: Bearer $TOKEN"
# 200 avec un jeton valide ; 401 avec un jeton trafiqué.
```

### S121 — isolation par org via le **claim** JWT (et non l'en-tête)
Deux jetons d'orgs différentes (claim `org_id` distinct) → chacun ne voit que SES données,
**sans** envoyer `X-Org-ID` (l'org vient du jeton, source de vérité) :
```bash
curl -s $B -H "Authorization: Bearer $TOKEN_ORG_A"   # données d'A
curl -s $B -H "Authorization: Bearer $TOKEN_ORG_B"   # données de B (disjointes)
```

### S121 — propagation `X-Forge-User-Token` vers le core Forge
L'adaptateur Forge propage le JWT user reçu (au lieu du token de service). Preuve **par
contraste** sur une route proxy de l'adaptateur (sans dépendre d'un appel d'outil du Cœur) :
```bash
# SANS en-tête → l'adaptateur tente un token de service via SON Keycloak → si absent : 502.
curl -s -w '\n[%{http_code}]\n' localhost:5700/agents
# AVEC en-tête → l'adaptateur SAUTE Keycloak et propage CE jeton au core (visible dans les
# logs du core : "GET /api/agents …"). Le code du core dépend de SA validation à lui.
curl -s -w '\n[%{http_code}]\n' localhost:5700/agents -H "X-Forge-User-Token: Bearer $TOKEN"
```
> ⚠️ **Limite connue (2026-06-29)** : le core Forge valide contre un Keycloak DIFFÉRENT
> (realm **`oria`** sur **:8081**, dont le `oria-realm.json` n'est pas dans ce repo) — donc
> « le core agit *vraiment* au nom du user » exige cette infra Oria + de vrais utilisateurs.
> Le **maillon S121** (Cœur émet → adaptateur capte+propage → core reçoit) est, lui,
> prouvable LIVE par le contraste ci-dessus (502 sans en-tête vs le jeton qui atteint le core).

---

# 8. Récapitulatif des preuves

| Sprint | Preuve LIVE | Niveau | Attendu |
|---|---|---|---|
| S114 | `len(openapi.paths)` | A | dépend des briques (≈93 complet ; 74 minimal) |
| S116 | santé briques | A | 200 partout |
| S118 | `import shared.llm_client` + appel LLM | A | JSON renvoyé |
| S119 | `/audits/{id}` via response_model | A | couches parsées |
| S120 | `import shared.workplace_auth` ; 401 sans jeton | A/B | OK / 401 |
| S120 | JWT valide → 200, trafiqué → 401 | B | OK |
| S121 | isolation `X-Org-ID` | A | orgB voit `[]` |
| S121 | colonne `org_id` + migration | A | colonne présente |
| S121 | propagation `X-User-Id` agenda | A | calendriers disjoints |
| S121 | isolation par claim JWT | B | orgs disjointes sans en-tête |
| S121 | propagation `X-Forge-User-Token` | B | acteur = user réel |

# 9. Dépannage (pièges connus)

- **`ENOSPC` / disque plein** : `docker system prune -af` (ajouter `--volumes` si on
  accepte de perdre les données de dev). Builder **une brique à la fois**.
- **Images périmées après un `git pull`** : toujours `docker compose up -d --build`
  (le launcher fait `up -d` SANS `--build` → images d'avant le commit).
- **Assistant « muet » / clé vide** : ne pas mettre `environment: VAR=${VAR:-}` qui
  écrase le `.env` racine par du vide (piège env-shadow). Vérifier que le `.env` racine
  est bien chargé (`docker compose config` montre les valeurs résolues).
- **500 au lieu de 401 quand Keycloak est injoignable** : `donnees`/`agenda` renvoient
  401 (jamais 500 silencieux) si le JWKS est joignable ; un JWKS injoignable côté agenda
  reste un 500 **pré-existant** (n'attrape que `JWTError`) — non régressé par S120/S121.
- **Port 5950 images/dev en conflit** : connu ; images a migré, vérifier le mapping.
- **`workplace_dev_ide` boucle EACCES** (`mkdir /home/coder/.config/code-server`) : le
  volume nommé `dev_dev_ide_config` est créé par Docker avec `root:root`. code-server
  tourne en UID 1000 (`coder`) et ne peut pas y écrire. Fix one-shot après le premier
  `docker compose up` de la brique `dev` :
  ```bash
  sudo chown 1000:1000 /var/lib/docker/volumes/dev_dev_ide_config/_data
  cd ~/workplace/briques/dev && docker compose up -d --force-recreate code-server
  ```

# 10. Après les preuves

Mettre à jour la mémoire d'épopée : remplacer « LIVE DIFFÉRÉ » par « PROUVÉ LIVE » pour
chaque preuve passée, en notant la date et la machine. Les sprints restants de l'épopée
(S122 briques atelier, S123 front/assets, S124 nettoyage/doc) suivent le même régime.
