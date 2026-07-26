# S198 — Brique tableur collaboratif (évaluation `suitenumerique/calc`)

> Plan d'implémentation — **pas de code, pas de commit**. Recherche faite sur le vrai code
> (`gh repo clone suitenumerique/calc`, profondeur 1, cloné dans le scratchpad, jamais copié
> dans le repo Workplace).

## Risques / Décisions à trancher (à lire en premier)

### Arbitrage : **Option B retenue — ne pas intégrer maintenant**

**Recommandation** : ne pas brancher `calc` au Workplace dans l'immédiat. Consigner ce sprint
comme **backlog YAGNI** (même logique que S192 dans la mémoire du projet), à réactiver **si et
seulement si** un besoin concret de tableur collaboratif apparaît (client qui le demande,
usage interne récurrent identifié). Le plan d'exécution complet (Option A) est documenté
plus bas, prêt à être repris tel quel le jour où l'arbitrage bascule — aucun travail de
cadrage à refaire.

**Pourquoi B plutôt que A, avec les chiffres trouvés en clonant le vrai repo :**

1. **Aucun besoin exprimé.** Ni la mémoire du projet (`MEMORY.md`, ~90 entrées) ni `WORKPLACE.md`
   ne mentionnent une demande de tableur avant ce sprint. Le sprint a été commandé pour
   *évaluer* l'idée (veille GitHub), pas en réponse à un usage bloqué.
2. **Poids infra disproportionné par rapport à toute autre brique du projet.** `calc` est un
   fork de `docs` (Django REST Framework + Next.js + Yjs/HocusPocus), pas une petite appli.
   Le déployer *tel quel* ajoute **7 à 9 conteneurs supplémentaires qui tournent en continu**
   (détail plus bas) — plus que n'importe quelle brique existante, Forge (la plus grosse à ce
   jour, ~28 400 lignes) inclus, qui elle n'ajoute « que » 3 conteneurs (db + core + frontend).
3. **Aucun déploiement Docker Compose de production n'est documenté par l'éditeur.** Le seul
   guide de déploiement officiel (`docs/installation.md` du repo `calc`) s'intitule
   *« Installation on a k8s cluster »* et suppose Helm + un cluster k8s (même en test, via
   `kind`). Le `docker-compose.yml` à la racine du repo est explicitement qualifié par le
   README de *« for testing purposes only »* (Mailcatcher en guise de SMTP, config Django
   `Demo`, pas `Production` durcie). Migrer ce compose en quelque chose d'hébergeable sur le
   HP (mono-serveur, sans k8s) est un travail réel de durcissement, non trivial, non couvert
   par la doc amont — donc pas juste du "docker compose up".
4. **La complexité forkée n'est pas la complexité utile.** Sur ~52 480 lignes de code
   (`src/`), l'essentiel vient de `docs` (éditeur de texte collaboratif, gestion de
   documents, admin Django, permissions, partages…) — **pas** de la logique tableur, qui
   tient dans un seul composant (`IronCalcEditor.tsx`) chargeant le moteur `@ironcalc/workbook`
   en **WASM côté navigateur** (confirmé : `import { IronCalc, Model, init } from
   '@ironcalc/workbook'`, aucun micro-service de calcul serveur). Intégrer `calc`, c'est donc
   héberger un **éditeur de documents collaboratif complet** pour n'en utiliser qu'une facette.
5. **Réversibilité de l'arbitrage.** Ne rien coder maintenant ne ferme aucune porte : le
   sprint reste consigné, chiffré, prêt à exécuter. Le coût de l'attente est nul ; le coût
   d'une intégration prématurée (opérer 7-9 conteneurs de plus, dont un Keycloak/Postgres
   redondants possibles) est réel et continu (RAM, mises à jour de sécurité Django/Next,
   support).

**Ce qui ferait basculer vers Option A** : un besoin concret et récurrent de tableur partagé
(ex. devis/factures chiffrés côté Forge qui gagneraient à s'éditer en tableur plutôt qu'en
formulaire, ou une demande explicite de l'utilisateur/d'un client). Dans ce cas, l'exécution
suit directement la section « Option A — plan d'exécution » ci-dessous, avec un point
d'optimisation déjà identifié : **réutiliser le Keycloak existant de Workplace (realm
dédié) au lieu d'en déployer un second**, ce qui ramène le delta à 7 conteneurs au lieu de 9.

**Ce que je NE recommande PAS** : forker/modifier le code de `calc` pour le faire rentrer
dans le moule d'une brique FastAPI légère. Le produit n'a de valeur que complet (édition
collaborative temps réel via Yjs/HocusPocus, permissions de partage, historique) — le
retailler casserait justement ce qui fait sa valeur. Si on l'intègre, ce doit être **tel
quel**, en iframe, jamais en réécriture partielle.

---

## Contexte technique établi par la recherche sur le vrai code

Recherche faite via `gh repo clone suitenumerique/calc /tmp/…/calc-research -- --depth 1`
(commit HEAD au 2026-07-25). Constats vérifiés directement dans le code, pas déduits :

### IronCalc = moteur de calcul **client-side WASM**, pas un service serveur
- `src/frontend/apps/impress/package.json` : dépendance `"@ironcalc/workbook": "0.5.5"`.
- `src/frontend/.../components/IronCalcEditor.tsx` : `import { IronCalc, Model, init } from
  '@ironcalc/workbook'` puis `init().then(...)` — le moteur de calcul (écrit en Rust,
  compilé en WASM) tourne **dans le navigateur** de chaque utilisateur. Le contenu de la
  feuille est sérialisé et persisté côté serveur comme un `Doc` classique (même modèle que
  `docs`), pas recalculé côté serveur.
- Conséquence pratique : **pas de micro-service « moteur de calcul » à héberger** — la seule
  charge serveur est celle de `docs` (Django + collaboration Yjs), identique à un déploiement
  de l'éditeur de texte. C'est le point le plus favorable trouvé pour Option A.

### Taille réelle du fork
- Dépôt cloné : 28 Mo, 645 fichiers sous `src/`, ~52 480 lignes (py/ts/tsx/js confondues).
- Diff avec `docs` (non mesuré ligne à ligne ici, mais visible à l'inspection) : `calc` ajoute
  essentiellement `IronCalcEditor.tsx` + le branchement dans `DocEditor.tsx` + la dépendance
  `@ironcalc/workbook`. Le reste (backend Django REST, permissions, partages, admin,
  traductions, Helm charts) est hérité tel quel de `docs`. **Ce n'est pas 52k lignes de
  travail spécifique tableur** — c'est l'héritage complet d'une appli de documents.

### Services du `docker-compose.yml` (racine du repo, profil dev/démo)
| Service | Rôle | Nécessaire en « prod » mono-serveur ? |
|---|---|---|
| `postgresql` | DB principale Django | Oui |
| `redis` | Cache + broker Celery + pub/sub collaboration | Oui |
| `minio` + `createbuckets` (job one-shot) | Stockage S3-compatible (fichiers/médias) | Oui (ou S3 externe si dispo) |
| `app` (Django, gunicorn, config `Demo`→`Production` à adapter) | API REST | Oui |
| `celery` | Tâches async (mail, traitement doc) | Oui |
| `y-provider` | Serveur Node.js HocusPocus (Yjs, édition temps réel) | Oui |
| `nginx` | Reverse-proxy interne (routes API/front/Keycloak) | Oui (ou remplacé par le proxy Workplace) |
| `frontend` (Next.js) | UI | Oui |
| `keycloak` + `kc_postgresql` | OIDC dédié dev | **Non si réutilisation du Keycloak Workplace existant** (voir plus bas) |
| `mailcatcher` | Faux SMTP dev | Non (remplacer par la brique `mail` ou un vrai SMTP) |
| `crowdin`, `node` | Outillage traduction dev | Non |
| `app-dev`, `celery-dev` | Variantes hot-reload dev | Non (utiliser les cibles `*-production` du Dockerfile) |

**Total réaliste pour un déploiement autonome** : **7 conteneurs longue durée**
(postgresql, redis, minio, app, celery, y-provider, frontend) **+ nginx** si on ne route pas
directement par le proxy existant de Workplace, **+ 2 si Keycloak dédié** (déconseillé, voir
ci-dessous) = **7 à 9 conteneurs**, contre 2-3 pour la plupart des briques Workplace et 3 pour
Forge (la plus grosse brique actuelle).

### Documentation de déploiement officielle = Kubernetes uniquement
`docs/installation.md` du repo (titre exact : *« Installation on a k8s cluster »*) est le
**seul** guide de déploiement fourni par l'éditeur. Il suppose un cluster k8s (test via `kind`
+ Helm), des charts Bitnami pour Postgres/Redis/Minio/Keycloak, et un chart Helm officiel
(`helm repo add impress https://suitenumerique.github.io/docs/`). **Rien n'est documenté pour
un Docker Compose de production autonome** — le compose à la racine est explicitement dev/démo
(README : *"for testing purposes only"*). Un déploiement Compose mono-serveur est *possible*
(le Dockerfile a des cibles `backend-production`/`frontend-production`, et Django a une classe
`Production(Base)` dans `settings.py`), mais c'est un travail d'adaptation **non couvert par
la doc amont**, à durcir soi-même (vrai SMTP, secrets, config `Production` au lieu de `Demo`,
retrait de mailcatcher/crowdin/node).

### Auth — Keycloak déjà présent chez Workplace, réutilisable en principe
- Workplace fait déjà tourner un Keycloak partagé (port hôte `8081`), realm `oria` (utilisé
  par Forge, agenda, generateur) et un realm `forge` pour le login du dashboard du Cœur
  (S171). Ce n'est **pas** une brique `briques/*` classique mais un service d'infra partagé
  (`oria-stack/`).
- `calc` utilise `mozilla-django-oidc` avec des variables génériques
  (`OIDC_OP_JWKS_ENDPOINT`, `OIDC_OP_AUTHORIZATION_ENDPOINT`, `OIDC_RP_CLIENT_ID`,
  `OIDC_RP_CLIENT_SECRET`, `OIDC_RP_SCOPES="openid email"`) — **compatibles en théorie** avec
  n'importe quel realm Keycloak existant, y compris `oria`.
- **Recommandation si Option A est un jour activée** : créer un **nouveau client OIDC** dans
  le realm `oria` existant (ex. client `calc`, public, PKCE) plutôt que déployer le second
  couple `keycloak`+`kc_postgresql` du compose amont. Économise 2 conteneurs. Risque à vérifier
  concrètement (non testé ici) : `calc` attend le scope `email` et un claim standard — devrait
  passer, mais le mapping exact des groupes/rôles Django (superuser, permissions de partage)
  n'a pas été audité en profondeur ; c'est un point de vérification du chantier 2 si activé.

### Estimation RAM/CPU (mono-serveur HP, ordre de grandeur — pas mesuré en vrai)
Pas de fiche RAM du HP dans les docs projet (`Proxmox HP 800 G4 i7-8700`, mémoire du projet) —
seulement le nombre de conteneurs actuels (~54, tous healthy). Estimation par service basée
sur des footprints standards Docker (pas de benchmark réel effectué) :

| Service | RAM idle estimée |
|---|---|
| postgresql | 150-300 Mo |
| redis | 30-60 Mo |
| minio | 150-300 Mo |
| app (Django/gunicorn) | 200-400 Mo |
| celery (worker) | 150-300 Mo |
| y-provider (Node/HocusPocus) | 100-200 Mo |
| frontend (Next.js prod) | 200-400 Mo |
| nginx (si gardé) | ~20 Mo |
| **Total** | **~1-2 Go idle**, plus sous charge d'édition collaborative active |

CPU : IronCalc tournant en WASM **côté client**, la charge serveur reste celle d'un éditeur
de documents classique (raisonnable au repos, pics sur upload/traitement Celery). Pas de
calcul lourd côté serveur attendu.

---

## Option A — plan d'exécution (prêt à activer, non exécuté dans ce sprint)

Si l'arbitrage bascule un jour, voici le déroulé — suit le contrat `GUIDE-ajouter-une-brique.md`
et le pattern déjà prouvé 4x dans Workplace (Forge, Studio, Personnages, atelier-veille) pour
une grosse appli tierce embarquée en iframe.

### Chantier 0 — décision d'architecture (déjà pris ci-dessus si activé)
- Brique **frontend-only** au sens du contrat (`couche: "frontend"`, `port: null` toléré côté
  manifest pour le Cœur) : le vrai point d'entrée exposé au dashboard est le **port hôte
  6200** (`Nginx`/`frontend` Next.js de `calc`), les services internes (postgres, redis,
  minio, celery, y-provider) gardent leurs ports internes au réseau Docker de la brique,
  jamais exposés au LAN.
- Vérifié : **6200 libre** — tous les manifests actuels (`briques/*/manifest.json`) plafonnent
  à 6160 (`atelier-images-video`). Aucune collision.

### Chantier 1 — dossier `briques/tableur/` (nom proposé, à valider)
1. `manifest.json` minimal :
   ```json
   {
     "nom": "tableur",
     "version": "0.1.0",
     "description": "Tableur collaboratif temps réel (fork suitenumerique/calc, IronCalc WASM). Aucune capacité pilotable — brique frontend embarquée en iframe.",
     "role": "tableur",
     "couche": "frontend",
     "statut": "a_tester",
     "port": null,
     "url_sante": null,
     "depends_on": [],
     "capacites": []
   }
   ```
   — cohérent avec `app-builder/manifest.json` (seul autre exemple `couche: frontend, port:
   null` du repo). Pas de `capacites` : rien à piloter depuis l'assistant, c'est un outil que
   l'utilisateur ouvre et utilise directement (comme Studio/Personnages).
2. `docker-compose.yml` de la brique : **vendoriser** (submodule ou copie versionnée du repo
   `calc` à un tag figé, jamais `main` mouvant) les cibles `backend-production` et
   `frontend-production` du `Dockerfile` amont, plus les services `postgresql`/`redis`/`minio`
   /`celery`/`y-provider`, tous sur un réseau Docker **interne** à la brique (pas de ports
   hôte sauf le frontend sur `6200`). Retirer `mailcatcher`/`crowdin`/`node`/`app-dev`
   /`celery-dev`/`keycloak`/`kc_postgresql` du compose de dev (garder Keycloak = celui déjà
   présent chez Workplace, realm `oria` + nouveau client `calc`).
3. Config Django à basculer sur `DJANGO_CONFIGURATION=Production` (pas `Demo`), secrets réels
   au `.env` (jamais commités), SMTP réel via la brique `mail` existante de Workplace plutôt
   que Mailcatcher.
4. Chemin de mise à jour amont : figer un tag/commit du repo `calc` dans un
   `CALC_UPSTREAM_REF` documenté (le fork évolue, pas de suivi automatique de `main`).

### Chantier 2 — SSO Keycloak
1. Nouveau client OIDC dans le realm `oria` existant (public, PKCE S256, `redirectUris`
   incluant `http://<host>:6200/*`).
2. Pointer les variables `OIDC_OP_*` du service `app` de `calc` sur `http://host.docker.internal:8081/realms/oria/...`.
3. **Vérification à faire réellement à ce moment-là** (pas garantie par la doc) : le mapping
   des groupes/permissions Django de `calc` avec les claims du token `oria` — c'est le point
   de risque technique principal, non validé par cette recherche (pas de déploiement réel
   testé).

### Chantier 3 — branchement dashboard (pattern Studio, ~3 points de code Cœur)
Ce point contredit légèrement le slogan « zéro code Cœur » du guide, mais c'est l'exception
**déjà documentée et utilisée 4x** pour l'UI embarquée (Forge/Studio/Personnages/atelier-veille),
pas une nouveauté :
1. `core/urls_ui.py` : ajouter `"TABLEUR": (6200, "/")` au dict `BRIQUES_UI`.
2. `core/routers/dashboard.py` : ajouter une tuile dans le Hub Créations (pattern
   `creation-tuile` / `ouvrirCreation('__TABLEUR_UI_URL__', 'Tableur')`, `.replace(...)`
   identique à celui de Studio ligne 746/3513).
3. `Lancer Workplace.command` : ligne `tableur|$RACINE/briques/tableur|http://localhost:6200/`.

### Chantier 4 — preuve
1. `make smoke` — valide le manifest hors-ligne.
2. `docker compose -f briques/tableur/docker-compose.yml up -d --build` → `curl :6200` → 200.
3. Dashboard `:5100` → tuile Tableur → SPA `calc` s'affiche, login OIDC realm `oria`, création
   d'une feuille, édition d'une formule (`=A1+A2`) → recalcul WASM visible, persistance après
   rechargement.

### Effort estimé si Option A activée
- Chantier 1 (compose + Dockerfile prod) : le plus long, adaptation non documentée par
  l'amont, à considérer comme **plusieurs jours** de travail réel (pas une demi-journée), du
  fait de l'absence de guide Compose de prod officiel.
- Chantier 2 (SSO) : incertitude sur le mapping claims/permissions — prévoir un cycle
  d'itération.
- Chantier 3 (branchement dashboard) : rapide, pattern déjà prouvé 4 fois, quelques heures.
- Chantier 4 (preuve) : dépend de la stabilité obtenue en chantier 1/2.

**Rapport effort/valeur** : élevé en effort (fork Django+Next.js entier à opérer et maintenir
à jour de sécurité), valeur incertaine (aucun besoin exprimé à date). C'est la base
quantitative de la recommandation Option B ci-dessus.

## Option B — actions concrètes de ce sprint
1. Ce document sert de mémoire du chantier (pas de code touché, pas de commit).
2. Prochaine étape suggérée hors-sprint : ajouter une ligne dans `MEMORY.md` du type
   *« S198 — tableur collaboratif (calc/IronCalc) : évalué, YAGNI, backlog si besoin concret »*
   pour éviter de re-explorer le même terrain à la prochaine veille GitHub qui retombe sur
   `suitenumerique/calc`.
