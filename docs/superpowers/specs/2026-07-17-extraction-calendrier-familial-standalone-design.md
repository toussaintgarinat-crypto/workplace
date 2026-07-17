# Extraction « Calendrier Familial » — dépôt auto-hébergeable — design

Date : 2026-07-17
Périmètre : extraire la brique `agenda` de Workplace dans son propre dépôt GitHub
public auto-hébergeable, **tout en la gardant** comme brique dans Workplace.
Modèle de distribution : open-source auto-hébergé (vraiment gratuit à opérer),
fidèle à la démarche souveraine.

## But

Permettre à n'importe qui de lancer l'agenda familial chez soi (`docker compose up`)
sans dépendre du reste de Workplace, et de le proposer gratuitement. La brique agenda
est déjà une application autonome (app web `/app`, auth propre `calendar-app`, base
propre, PWA S178, chiffrement au repos S180). Ce sprint la conditionne en produit
distribuable, sans casser son usage dans Workplace.

## Couplage mesuré (2026-07-17)

L'agenda est quasi-intégralement autonome :
- **Une seule dépendance externe** : `from shared.workplace_auth import KeycloakSettings,
  has_role, verify_token` (dans `backend/auth.py`, un seul site). `shared/workplace_auth.py`
  = 1 fichier, 5,8 Ko, **zéro dépendance non-stdlib**.
- Paquet vendored `briques/agenda/shared` (installé en `agent_personnel_shared`, 60 Ko,
  6 fichiers) — déjà sous l'arbre de l'agenda.
- Front : assets Leaflet **vendorés localement** (S179) ; les seuls appels externes au
  runtime sont les **tuiles de carte** IGN Géoplateforme / OpenStreetMap (inhérent à toute
  carte, services publics).
- **Aucun import** de `core`, d'autres briques, ni d'ailleurs (vérifié par grep).

## Décisions produit (validées avec l'utilisateur)

- **Nom / dépôt** : « Calendrier Familial » → `calendrier-familial`.
- **Licence** : Apache-2.0.
- **Auth par défaut** : mono-user out-of-box (`AUTH_ENABLED=false`) + profil Keycloak
  optionnel pour le partage familial.
- **Synchro** : Workplace reste la **source de vérité** ; un script `export-standalone.sh`
  copie le code vers le dépôt standalone.

## 1. Structure du dépôt standalone

```
calendrier-familial/
├── backend/                      # copie VERBATIM de briques/agenda/backend/
│                                 #   main.py, models/, routers/, services/, static/,
│                                 #   templates_app.py, crypto.py, alembic/, tests/, …
├── vendor/
│   ├── agent_personnel_shared/   # copie de briques/agenda/shared (paquet pip -e)
│   └── shared/
│       ├── __init__.py
│       └── workplace_auth.py     # le seul fichier de shared/ utilisé
├── keycloak/
│   └── realm-calendrier.json     # realm pré-semé (client calendar-app) — profil multi
├── Dockerfile                    # chemins COPY adaptés au contexte standalone
├── docker-compose.yml            # service agenda (défaut) + profile "multi"
├── entrypoint.sh                 # auto-génère VAULT_SECRET au 1er boot (§3)
├── .env.example
├── README.md
├── LICENSE                       # Apache-2.0
└── NOTICE
```

**Clé de l'autonomie** : on **préserve les chemins d'import** (`shared.workplace_auth`,
`agent_personnel_shared`) en les plaçant sous `vendor/` et en reproduisant le montage du
Dockerfile Workplace. Conséquence : **zéro modification du code de `backend/`** → la
synchro reste une pure copie, aucune divergence de logique.

## 2. Dockerfile (adapté)

Repris du Dockerfile Workplace (`briques/agenda/backend/Dockerfile`) avec le contexte de
build = **racine du dépôt standalone** :
- `COPY vendor/agent_personnel_shared /opt/agent_personnel_shared` + `pip install -e`.
- `COPY vendor/shared/ /app/shared/` (rend `shared.workplace_auth` importable).
- `COPY backend/requirements.txt` + install, puis `COPY backend/ ./`.
- `ENTRYPOINT ["/app/entrypoint.sh"]` puis `CMD ["uvicorn", "main:app", "--host",
  "0.0.0.0", "--port", "8400"]` (entrypoint délègue au CMD après init).
- Reste identique : user non-root `appuser`, `EXPOSE 8400`, healthcheck `/health`.

## 3. docker-compose — deux modes + chiffrement

**Défaut (mono-user)** : un service `agenda` (build `.`, `ports 8400:8400`, volume nommé
`calendrier_data:/data`, `AUTH_ENABLED=false`, `ATTACHMENTS_DIR=/data/calendar/attachments`).
`docker compose up` → `/app` opérationnel immédiatement, sans compte.

**`docker compose --profile multi up`** : ajoute `keycloak` + `keycloak-db` (import de
`keycloak/realm-calendrier.json`, realm `calendrier`, client public `calendar-app` avec
redirect `http://localhost:8400/*`) ; l'agenda passe `AUTH_ENABLED=true`,
`KEYCLOAK_URL`/`KEYCLOAK_PUBLIC_URL=http://localhost:8080`, `KEYCLOAK_REALM=calendrier`,
`KEYCLOAK_AUDIENCE=calendar-app`.

**Intégrations optionnelles** (désactivées par défaut, repli honnête déjà codé) :
- Push web : `CONNEXION_URL`/`CONNEXION_KEY` vides → push désactivé.
- Digest email : `MAIL_URL`/`MAIL_KEY` vides → digest email désactivé.
- Documentées dans le README comme « brancher un pont de notifications ».

**Chiffrement au repos (§ argument produit)** : `crypto.py` (S180) est inclus, chiffrement
transparent AES-GCM des champs sensibles. `VAULT_SECRET` requis (fail-closed). Pour un
premier `up` qui marche sans footgun de sécurité, `entrypoint.sh` **génère et persiste**
un `VAULT_SECRET` aléatoire dans `/data/.secret_vault` au premier démarrage s'il n'est pas
fourni par l'environnement (au lieu de livrer un secret par défaut en clair). Si l'utilisateur
pose son propre `VAULT_SECRET` (ou `AGENDA_ENCRYPTION_KEY`) dans `.env`, il a priorité.

## 4. `export-standalone.sh` (dans Workplace)

Script idempotent, exécuté depuis la racine Workplace, argument = chemin du dépôt
standalone. Copie :
- `briques/agenda/backend/` → `<repo>/backend/` (hors `__pycache__`, `.pytest_cache`,
  `*.db`, `/data`).
- `briques/agenda/shared/` → `<repo>/vendor/agent_personnel_shared/`.
- `shared/workplace_auth.py` (+ un `shared/__init__.py` minimal) → `<repo>/vendor/shared/`.

Il **ne touche pas** aux fichiers possédés par le dépôt standalone (`Dockerfile`,
`docker-compose.yml`, `entrypoint.sh`, `.env.example`, `README.md`, `LICENSE`, `NOTICE`,
`keycloak/`). Re-synchro = rafraîchir le code, rien d'autre.

## 5. README (structure)

- Pitch : agenda familial souverain, auto-hébergé, gratuit (Apache-2.0), chiffré au repos.
- Démarrage rapide : `cp .env.example .env` → `docker compose up` → `http://localhost:8400/app`.
- Partage familial (multi-user) : `docker compose --profile multi up`, création de comptes.
- Intégrations optionnelles (push, digest, Google Agenda).
- Fonctionnalités (calendrier, événements récurrents, étiquettes, invitations, listes de
  courses, sondages, présence, cartes de fidélité, PWA, ICS/webcal, chiffrement au repos).
- Sauvegarde (le volume `calendrier_data` = base + secret + pièces jointes).

## 6. Vérification (preuves avant publication)

- `docker compose build` réussit dans le dépôt standalone.
- `docker compose up` (défaut) → `GET /health` = 200, `GET /app` charge en mono-user.
- Suite de tests de l'agenda (~341 passed) exécutée dans le contexte standalone
  (mêmes tests, code identique).
- `docker compose --profile multi up` → Keycloak démarre, realm `calendrier` importé,
  `/app` redirige vers le login.

## 7. Publication GitHub (étape gardée)

Le dépôt est construit et **prouvé en local d'abord**. La création + push du dépôt
**public** GitHub est une action externe irréversible → **confirmation explicite de
l'utilisateur** requise avant de pousser (nom `calendrier-familial`, visibilité publique,
licence Apache-2.0). Non fait tant que non confirmé.

## Hors périmètre (fast-follow)

- Version hébergée (SaaS freemium) — décision et sprint futurs.
- `lier_compte_perso.py` (utilitaire Workplace « perso ») : copié tel quel, inoffensif en
  standalone.
- CI (build + tests) sur le dépôt public — après la première publication.
- Traductions du README (EN) pour l'audience internationale.

## Contrainte

Aucune modification du code `backend/` (preuve d'autonomie = les mêmes tests passent sans
édition). Toute divergence future se gère par re-synchro depuis Workplace, jamais par un
patch direct dans le dépôt standalone.
