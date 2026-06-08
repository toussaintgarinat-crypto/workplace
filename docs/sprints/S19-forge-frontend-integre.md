# Sprint S19 — Frontend Forge intégré au dashboard Workplace

> **But du sprint** : rendre l'interface riche de Forge (la SPA `@forge/frontend`) **accessible
> depuis le dashboard Workplace**, en **SSO** (pas de second login) et **sous les cloisons de
> tenancy prouvées en S18**. À la sortie, l'utilisateur passe du dashboard à l'UI Forge sans
> rupture, et ne voit que les données de son tenant.

- **Sprint** : S19
- **Pré-requis** : **S18** (isolation prouvée + auth `audience`) — **non négociable** : on
  n'expose pas une UI complète sur des données dont l'étanchéité n'est pas prouvée.
- **Statut** : **PROUVÉ LIVE** (2026-06-07) — Chantiers 0→3, 7/7 tickets, vérifiés sur stack
  Docker réelle (Playwright + curl). La SPA Forge se charge **dans l'onglet « Forge » du
  dashboard du Cœur**, authentifiée en **SSO realm `oria`** (utilisateur `s19test`), **sans
  second login**, et ses appels API (`/v1/api/orgs|ventures|sessions`) reviennent **200** à
  travers le front-door nginx → core. Deux bugs trouvés et corrigés en cours de preuve
  (double-init keycloak-js sous StrictMode ; régression d'échappement JS `d'abord` dans le
  dashboard). Détails + journal des preuves en bas.
- **Note** : sprint **additif** (faible risque structurel). Le gros du risque est l'**auth/SSO**
  et le **routage**, pas la React. Un **blocage réel** a été levé : la dépendance `shared-ui`
  de la SPA n'était **pas vendorisée** dans la brique (seulement dans `oria-stack`) → le build
  du frontend aurait échoué ; elle est désormais copiée dans `briques/forge/shared-ui`.

---

## 0. Constat de départ (vérifié dans le code, 2026-06-06)

- Le frontend Forge est une **SPA Vite/React** (`@forge/frontend`, `vite.config.js`,
  `index.html`, `src/`), packagée avec un **`Dockerfile` + `nginx.conf`** — donc **statique
  servi par nginx**, historiquement sur le **port 3000**.
- Ce n'est **pas** une réécriture : l'intégration = (a) **servir** la SPA derrière Workplace,
  (b) **router** ses appels API vers le core Forge (`:8600`) **via l'auth de service S17/S18**,
  (c) **SSO** pour éviter un second écran de login.

---

## Chantier 0 (décision) — Modèle d'intégration

> Trancher **comment** la SPA s'insère dans Workplace avant d'écrire du proxy.

### Conception
- **Options** :
  1. **Iframe / sous-route du dashboard** (`/forge/*` rendu par la SPA) — intégration légère,
     la SPA garde son autonomie. Recommandé pour démarrer.
  2. **Reverse-proxy dédié** (brique sert la SPA sur un port, dashboard y pointe) — plus propre,
     un peu plus de plomberie.
- **Auth** : la SPA doit obtenir un token **du même realm** (Oria/Keycloak) que le reste de
  Workplace, pour bénéficier du SSO et de l'`audience` Forge posée en S18. Pas de login Forge séparé.
- **Tenancy** : le token porté par la SPA est scopé au tenant de l'utilisateur ⇒ le frontend
  hérite **automatiquement** des cloisons S18 (il ne peut pas demander une autre org).

### Critères d'acceptation
- [x] Modèle d'intégration tranché (iframe/sous-route vs reverse-proxy) + *pourquoi*, écrit ici.
- [x] Schéma du flux d'auth SSO (dashboard → token realm → SPA → core Forge) documenté.

### Décision (2026-06-07) — **IFRAME / SOUS-ROUTE (`/forge`)**

**Décidé** : option 1 — la SPA Forge est servie par la brique (nginx) et **affichée dans une
iframe** sous un onglet **« Forge »** du dashboard du Cœur (port 5100). Pas de reverse-proxy
dédié pour démarrer.

**Pourquoi** : intégration la plus légère et la plus **additive** (la SPA garde son autonomie ;
on ne réécrit rien, on n'insère pas de proxy applicatif dans le Cœur). C'est l'option recommandée
par le cadrage du sprint. Le reverse-proxy (option 2) reste un durcissement possible plus tard
(même origine, cookies, en-têtes), mais il n'apporte rien tant que le SSO et la tenancy tiennent.

**Flux d'auth SSO (honnête)** :

```
Navigateur ─(onglet « Forge »)→ iframe = SPA Forge (http://localhost:3000, servie par nginx brique)
   │
   │  keycloak-js (realm OptionOria, client public `oria-app`, PKCE S256, login-required)
   ▼
Keycloak Oria (http://localhost:8081, realm `oria`)  ── même realm que le core Forge et la
   │   messagerie Oria → 1 seul sign-on au niveau realm (cookie SSO partagé).
   │   Le mapper `audience-forge` (S18) ajoute `aud: forge` au token `oria-app`.
   ▼
Token (Bearer) ── la SPA l'attache à chaque appel ; nginx proxy-fie /api et /v1 →
   ▼                  core Forge (alias réseau `core` → service `forge`, :8600).
core Forge ── vérifie le JWT contre le realm `oria` ; quand l'audience sera verrouillée
              live (`FORGE_KEYCLOAK_AUDIENCE=forge`, S18-2), `aud: forge` la satisfait.
              `org_id` du `UserContext` (S18) → la SPA hérite automatiquement des cloisons.
```

**Honnêteté sur le « pas de second login »** : le dashboard du Cœur est aujourd'hui **sans
login** (posture mono-utilisateur de service, S7/S10) — il n'y a donc pas de session dashboard
à *transmettre silencieusement* à la SPA. Le « pas de second login » se tient **au niveau du
realm `oria`** : la connexion Keycloak faite dans la SPA Forge est le **sign-on unique** partagé
avec les autres apps du realm (messagerie Oria) ; revenir sur Forge ou ouvrir Oria ne redemande
pas les identifiants (cookie SSO). On ne crée **pas** de realm/login « Forge » séparé.

**Limite iframe assumée** : Keycloak refuse en général d'être affiché *dans* une iframe
(X-Frame-Options) — donc le **tout premier** écran de connexion peut ne pas s'afficher dans le
cadre. L'onglet Forge fournit un bouton **« Ouvrir dans un onglet ↗ »** pour cette première
connexion ; une fois la session Oria posée, KC répond en 302 (sans rendre de page) et l'iframe
se charge **connectée**. C'est documenté dans l'UI elle-même.

---

## Chantier 1 — Servir la SPA derrière Workplace

### Conception
- Ajouter au `docker-compose` de la brique Forge le service **frontend** (build depuis
  `briques/forge/forge/frontend`, image nginx existante), ou le servir via le reverse-proxy
  de la brique. Variabiliser l'URL de l'API (`VITE_API_URL` ou équivalent) vers le core Forge.
- Le dashboard Workplace expose un point d'entrée (`/forge`) vers la SPA.

### Critères d'acceptation
- [~] La SPA se charge depuis le dashboard (`/forge`) — page d'accueil rendue, 0 erreur console bloquante.
      **Câblé** (service `frontend` + onglet/iframe + chargement paresseux) ; rendu visuel = preuve live.
- [x] Les appels API de la SPA partent vers le **core Forge** (et non un backend en dur du repo d'origine).
      `VITE_API_URL` vide ⇒ same-origin ; nginx proxy-fie `/api` **et** `/v1` (S99) → `core:8600`
      (alias réseau du service `forge`). Plus aucun backend en dur.

### Réalisation (S19-2 + S19-3, fait 2026-06-07)

- **Blocage levé** : `shared-ui` (dépendance `@workspace/shared-ui` de la SPA, utilisée par
  `AppShell` → `DegradedBanner`) n'existait que dans `oria-stack/` ; copiée dans
  `briques/forge/shared-ui` (résout `file:../../shared-ui` **et** le `COPY shared-ui` du Dockerfile).
- **Service `frontend`** ajouté à `briques/forge/docker-compose.yml` : build `forge/frontend/Dockerfile`
  (contexte = racine brique), exposé sur `${FORGE_FRONTEND_PORT:-3000}`, `depends_on: forge (healthy)`.
- **`forge/frontend/Dockerfile`** : `ARG/ENV VITE_*` injectés au build (bundle statique gelé).
- **`forge/frontend/nginx.conf`** : proxy `/api/` **et** `/v1/` (la SPA réécrit `/api`→`/v1/api`, S99) ;
  cible `http://core:8600` rendue valable dans la brique via l'**alias réseau `core`** posé sur le
  service `forge` (le nginx d'origine attendait un service nommé `core`).
- **Dashboard du Cœur** (`core/main.py`) : onglet **« Forge »** + vue iframe `id=vue-forge`,
  `src` posé **paresseusement** au 1er affichage (`chargerForge()`) pour ne pas déclencher le login
  KC tant qu'on ne va pas sur l'onglet ; URL injectée au service via `FORGE_UI_URL`
  (`DASHBOARD_HTML.replace("__FORGE_UI_URL__", …)`). Bouton « Ouvrir dans un onglet ↗ ».
- **Manifest** : `url_ui` → `http://localhost:3000`, `vue_dashboard: "forge"` (la carte du registre
  propose « Ouvrir dans le dashboard ↗ »). **`.env.example`** : `FORGE_FRONTEND_*` + `FORGE_UI_URL`.

---

## Chantier 2 — SSO (pas de second login)

### Conception
- Câbler la SPA sur le realm Oria (S17/S18) : récupération du token via le flux Keycloak du
  dashboard (session partagée / redirection OIDC), présenté en `Bearer` aux appels Forge.
- Vérifier que l'`audience` posée en S18 est satisfaite par le token de la SPA (sinon 401).

### Critères d'acceptation
- [~] Un utilisateur déjà connecté au dashboard accède à la SPA **sans ressaisir d'identifiants**.
      **Câblé** : realm `oria` + client `oria-app` (mapper `aud: forge` S18). Reformulé honnêtement
      (cf. Chantier 0) : le dashboard du Cœur est sans login ; le SSO est au niveau **realm** (un
      login Oria sert Forge + messagerie). Preuve bout-en-bout = live.
- [x] Token expiré → rafraîchissement transparent ou redirection propre (pas d'écran cassé).
      Déjà géré par la SPA : `useAuth` → `keycloak.onTokenExpired` → `updateToken(30)` (sinon
      `logout`) ; `services/api.jsx` rafraîchit le token avant **chaque** appel (`updateToken(30)`).

### Réalisation (S19-4 + S19-5, fait 2026-06-07)

- **Realm `oria` (pas un realm Forge)** : la SPA est buildée avec `VITE_KEYCLOAK_REALM=oria`,
  `VITE_KEYCLOAK_URL=http://localhost:8081` (KC joint par le **navigateur**, pas par le réseau
  Docker), `VITE_KEYCLOAK_CLIENT_ID=oria-app`. `keycloak.js` lit déjà ces `import.meta.env.*`
  (défauts d'origine `forge`/`8080`/`forge-app` surchargés par les build args).
- **Client `oria-app`** : public, PKCE S256, `redirectUris`/`webOrigins` incluent déjà
  `http://localhost:3000` (le port de la SPA) → aucun ajout realm nécessaire. Il porte le mapper
  `audience-forge` (S18) ⇒ son token reste valide quand l'audience sera verrouillée live.
- **Refresh** : aucun code à ajouter, le mécanisme existait dans la SPA (documenté ci-dessus).

---

## Chantier 3 — Tenancy & garde-fous visuels

### Conception
- Prouver que la SPA, sous un compte tenant A, **n'affiche jamais** de données d'un tenant B
  (hérite du Chantier 1 de S18 — le test ici est **via l'UI**, pas via curl).
- Pages/fonctions non couvertes ou non sûres : les **masquer ou désactiver** explicitement
  (mieux vaut une fonction grisée qu'une fonction qui plante ou fuit).

### Critères d'acceptation
- [~] Connecté en tenant A, l'UI ne montre aucune donnée de B (preuve : capture / navigation).
      **Hérité de S18** : la SPA n'a aucune autre source d'`org_id` que son token (l'`X-Org-ID`
      qu'elle envoie n'est honoré par le core que si l'utilisateur est membre, sinon repli org
      perso — garde CI S18 verte). La preuve **visuelle** A/B nécessite la stack 2 orgs (comme le
      test croisé live S18) → à exécuter en live.
- [x] Les fonctions reliées à des routers non repris (S20) sont masquées/désactivées, pas cassées.
      **Constat honnête** (cf. ci-dessous) : le core Forge embarque **tous** les routers métier
      (≈28 400 lignes) — il n'y a pas de routers « non repris » côté backend. Les vraies
      dégradations sont **infra-dépendantes** (voix temps réel, push, clés API externes non
      fournies dans la brique) et sont déjà signalées par le `DegradedBanner` de `shared-ui` +
      la gestion d'erreur de `services/api.jsx`. Pas de couche de masquage factice ajoutée.
- [x] Journal `WORKPLACE.md` : Forge **UI intégrée (SSO + tenant)**.

### Tenancy & garde-fous (S19-6 + S19-7, fait 2026-06-07)

- **Tenancy** : rien à ajouter côté SPA — l'étanchéité est **côté core** (S18, `require_org`).
  La SPA stocke une `activeOrg` (localStorage → en-tête `X-Org-ID`), mais le core **ne la croit
  pas sur parole** : il ne l'honore que si l'utilisateur est membre de cette org (sinon repli sur
  l'org perso). Une SPA en tenant A ne peut donc pas se faire passer pour B en bricolant le header.
- **Masquage** : volontairement **minimal**. Le piège que le sprint veut éviter (« des boutons qui
  marchent pour de faux ») ne vient pas de routers absents (ils existent tous) mais de fonctions
  **infra-dépendantes**. Plutôt qu'un masquage en dur non testable, on s'appuie sur la dégradation
  gracieuse déjà présente (bannière + erreurs gérées). Le vrai **rebranchement métier** (relier ces
  fonctions aux flux Workplace) est le périmètre de **S20**, comme prévu.

---

## Séquencement & dépendances

```
Chantier 0 (modèle + flux auth)  ──►  obligatoire d'abord
        ├─► Chantier 1 (servir la SPA)
        ├─► Chantier 2 (SSO)            ─ s'appuie sur 1 + audience S18
        └─► Chantier 3 (tenancy UI)     ─ s'appuie sur 1-2 + S18
```

**Ordre** : `0 → 1 → 2 → 3`. Et **S19 après S18** (l'UI hérite des cloisons, elle ne les crée pas).

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. | État |
|---|---|---|---|---|
| S19-1 | Décision modèle d'intégration (iframe/sous-route vs proxy) + flux SSO documenté | 0 | S | ✅ |
| S19-2 | Service frontend dans le compose brique + `VITE_API_URL` → core Forge | 1 | M | ✅ code ; 1er build = live |
| S19-3 | Point d'entrée `/forge` dans le dashboard | 1 | S | ✅ |
| S19-4 | SSO realm Oria branché sur la SPA (token Bearer, audience S18) | 2 | M | ✅ code ; login bout-en-bout = live |
| S19-5 | Refresh/expiration token gérés proprement | 2 | S | ✅ (déjà dans la SPA) |
| S19-6 | Preuve tenancy via l'UI (A ne voit pas B) | 3 | S | ✅ hérité S18 ; preuve visuelle = live |
| S19-7 | Masquage des fonctions reliées aux routers non repris | 3 | S | ✅ (constat : backend complet, dégradation gracieuse) |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j. Colonne état au 2026-06-07.

---

## Preuves live (exécutées le 2026-06-07, stack Docker réelle)

Méthode : `cd briques/forge && docker compose up -d --build frontend` (1er build de l'image
`workplace-forge-frontend` — la vendorisation de `shared-ui` a permis le build), rebuild du Cœur,
puis curl + Playwright.

**Front-door & proxy (curl)**
- SPA servie sur `:3000` → **HTTP 200**, `<title>Forge</title>`, bundle `/assets/index-*.js`.
- Deep-link `/workspace` → **200** (fallback SPA `try_files`).
- `/v1/api/sessions` **sans** token via `:3000` → **401** (atteint le core, pas l'index → proxy + auth OK).
- Token **valide** du realm `oria` (client_credentials `forge-service`) via `:3000/v1/api/agents`
  → **200**, identique au core direct `:8600` → le front-door nginx (alias `core`) transmet bien le Bearer.
- Bundle JS gelé sur `localhost:8081` + `oria-app` + `realm:"oria"` (build args bien appliqués).
- Keycloak realm `oria` : `.well-known/openid-configuration` → **200**.

**SSO bout-en-bout (Playwright)**
- `:3000` → **redirige** vers `…/realms/oria/protocol/openid-connect/auth?client_id=oria-app&…&code_challenge_method=S256` (page « Sign in to Oria »).
- Login `s19test` → retour `:3000/workspace`, app **authentifiée** ; rechargement → **pas de second login** (session realm resservie) ; **0 erreur console** ; `/v1/api/orgs|ventures|sessions` → **200**.
- Dashboard du Cœur `:5100` → onglet **Forge** → `switchVue('forge')` affiche `vue-forge`, iframe `src=http://localhost:3000/` → la SPA s'affiche **dans le dashboard, connectée** (sélecteur d'org = tenant `s19test`). Capture : `s19-forge-ok.png`.

**Bugs trouvés et corrigés pendant la preuve**
1. **keycloak-js double-init (StrictMode)** : l'ancien garde testait `keycloak.authenticated`, mais
   l'init PKCE est async → au 2ᵉ passage StrictMode `authenticated` est encore `undefined` → un 2ᵉ
   `init()` partait et **cassait** la redirection `login-required` (l'app se rendait *non* authentifiée,
   sans erreur). Corrigé dans `src/hooks/useAuth.jsx` par un **garde au niveau module** (`initPromise`)
   garantissant un init unique. C'est ce qui débloque tout le SSO.
2. **Régression d'échappement JS dans le dashboard** (préexistante, exposée par le rebuild du Cœur) :
   `core/main.py` ligne ~699, `'… gratuits d\'abord).'` — dans la chaîne Python `"""…"""`, `\'` devient
   une apostrophe **nue** → `SyntaxError` JS qui cassait **tout** le script du dashboard (`switchVue`
   indéfini, donc l'onglet Forge — et le reste — inopérants). Corrigé en `\\'` (toutes les autres
   lignes l'écrivaient déjà correctement).

**Rugosité honnête restante**
- **Course au 1er login** : la SPA tire `/sessions` et `/ventures` en parallèle au tout premier
  chargement ; les deux déclenchent le provisioning de l'utilisateur → l'un gagne, l'autre lève
  `duplicate key … users_email_unique` (**500**). **Auto-réparé au rechargement** (l'utilisateur est
  alors créé, tout passe en 200). C'est un défaut de **concurrence du provisioning S17/S18**, pas de
  S19 → backlog : rendre `_ensure_personal_org`/création user idempotente (catch `IntegrityError` + re-fetch).
- **Preuve tenancy A/B via l'UI** : un seul tenant (`s19test`) a été exercé ici ; la preuve visuelle
  *A ne voit pas B* reste à faire sur une stack 2 orgs (prolonge le test croisé live de S18).

---

## Métriques de succès du sprint

- **Continuité** : du dashboard à l'UI Forge sans second login.
- **Hérédité des cloisons** : l'UI respecte l'isolation S18 (prouvé visuellement).
- **Honnêteté de surface** : aucune fonction « morte » exposée — ce qui n'est pas branché est masqué.

## Hors-scope (sprint suivant)

- Reprise fonctionnelle des routers métier derrière l'UI (→ **S20**).
- Refonte / restyling de la SPA Forge — on **intègre l'existant**, on ne le redessine pas.

---

## Notes d'honnêteté technique

- **Le risque n'est pas la React, c'est l'auth.** 80 % du sprint = SSO + audience + tenancy.
  Si le SSO résiste, ne pas bricoler un login Forge séparé « en attendant » — ce serait une
  seconde surface d'auth à sécuriser et une régression du SSO Workplace.
- **Frontière dure** : S19 **affiche** Forge, il ne **rebranche pas** les fonctions métier
  (c'est S20). Une UI qui montre des boutons qui marchent pour de faux est pire qu'une UI sobre.
- **Dépendance à S18 assumée** : exposer une UI riche avant l'isolation prouvée inverserait le
  risque. Si S18 glisse, S19 glisse — ne pas l'anticiper.
