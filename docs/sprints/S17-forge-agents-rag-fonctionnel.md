# Sprint S17 — Forge fonctionnel end-to-end (palier 3 : agents + RAG prouvés)

> **But du sprint** : prouver, bout-en-bout et depuis l'assistant du Cœur, que Forge
> **fait** ce pour quoi il existe — lancer un agent qui raisonne via la **Gateway** Workplace,
> et un cycle **RAG** (ingérer un document → l'interroger). C'est ici que vit la valeur des
> ~28 400 lignes de Forge. À la sortie de ce sprint, le 🟡 historique « à tester » devient un
> 🟢 **fonctionnel prouvé**, pas seulement « le core répond ».

- **Sprint** : S17
- **Pré-requis** : **S16** (Forge intégré, adaptateur, **voie d'auth tranchée**)
- **Statut** : **planifié** (2026-06-06)
- **Note** : sprint **lourd** (auth + schéma DB + base vectorielle + évaluation qualité).
  Ne pas démarrer avant que la note de décision d'auth de S16 soit écrite et un appel
  authentifié prouvé à la main.

---

## 0. Note de décision d'auth (tranchée en sortie de S16 — 2026-06-06)

> **Voie retenue** : **2 — token Keycloak de service (client_credentials) via le Keycloak d'Oria**.
> **Pourquoi** : c'est la seule voie qui (a) **ne touche pas** au code du core Forge — on réutilise
> le chemin `get_current_user` déjà testé (parité Bun) au lieu de le forker ; (b) **réutilise une
> infra déjà debout** (Keycloak d'Oria, `:8081`) sans en lever une nouvelle ; (c) s'inscrit dans le
> motif **multi-tenant S14** : `verify_token` ne vérifie ni l'issuer ni l'audience (audience vide ⇒
> `verify_aud=False`), donc **tout JWT signé par le realm configuré est accepté** — un token de
> service suffit, sans flux interactif. L'assistant du Cœur est mono-utilisateur ; un **compte de
> service unique** (provisionné en un user Forge + org perso au 1er appel) est le bon grain.

**Voies écartées :**
- **1 — api_keys de service** : ❌ le router `api_keys` du core gère des **clés provider LLM**
  (OpenAI, Anthropic…) **par utilisateur**, et il est lui-même protégé par `get_current_user`.
  Ce n'est **pas** un mécanisme d'auth machine-à-machine. Aucune clé de service native.
- **3 — identité par en-tête (X-User-Id, auth off)** : ❌ `app/auth.py` n'a **aucun** bypass ;
  l'implémenter = **forker le core** (dette + divergence de la parité Bun soigneusement maintenue)
  et **affaiblir la sécurité** (confiance dans un en-tête) sur un service qui porte de vraies
  données multi-org. À éviter.

**Preuve S16 (faite à la main, 2026-06-06)** — voie 2 prouvée au niveau auth :
1. Client service `forge-service` créé dans le realm `oria` (`serviceAccountsEnabled`), via l'API
   admin Keycloak (sans redémarrage). Token obtenu par `grant_type=client_credentials` sur
   `:8081/realms/oria/protocol/openid-connect/token` (issuer `…/realms/oria`, `azp=forge-service`).
2. Forge pointé temporairement sur ce Keycloak (`KEYCLOAK_URL=:8081`, `KEYCLOAK_REALM=oria`), puis
   `GET :8600/api/agents` :
   - **sans token → 401** ; **token bidon → 401** (la **signature** est bien vérifiée via JWKS) ;
   - **token de service valide → 500** : l'auth est **franchie** (provisioning user déclenché),
     le 500 est `relation "users" does not exist` — c.-à-d. **uniquement le schéma DB non migré**,
     qui est précisément un livrable de **ce** sprint (cf. § ci-dessous, migrations). Aucune barrière
     d'auth restante.
3. Forge **remis à l'état S16 « sans auth »** après la preuve (`KEYCLOAK_URL` vide ; `/api/agents`
   re-verrouillé en 401). S16 reste une frontière dure « sans auth ».

**À faire en S17 (découle de la preuve) :**
- **Persister** le client `forge-service` dans `oria-stack/oria/keycloak/oria-realm.json` (créé en
  runtime = éphémère, disparaît au ré-import du realm). Y mettre le secret via env, pas en clair.
- Câbler `KEYCLOAK_URL`/`KEYCLOAK_REALM` du core Forge (compose) + faire que **l'adaptateur**
  `briques/forge/main.py` obtienne/rafraîchisse le token de service et le présente en `Bearer` sur
  chaque route protégée qu'il proxifie (`/agent/lancer`, `/rag/ingerer`, `/rag/chercher`).
- Appliquer les **migrations** du schéma Forge (sinon 500 même authentifié — cf. preuve).

Le reste du sprint suppose cette voie. Tous les appels de l'adaptateur Forge l'utilisent
de façon **machine-à-machine** (l'assistant du Cœur = mono-utilisateur « perso », cohérent
avec la brique `agenda`).

---

## 1. Contexte — ce qui manque pour le fonctionnel

| Dépendance | État S15/S16 | Requis S17 |
|---|---|---|
| Auth (Keycloak / get_current_user) | non franchie | **token/clé de service** sur chaque appel protégé |
| Schéma DB Forge (tables agents, documents, ventures…) | **non migré** (Postgres simple vide) | **migrations** appliquées (Alembic ou équivalent Forge) |
| Base vectorielle RAG | `QDRANT_URL` vide (désactivé) | **Qdrant** levé + `ML_MODULE_URL` (embeddings) câblé |
| LLM | Gateway 4001 branché ✅ | inchangé (réutilisé) |
| Mémoire | brique Mémoire 5600 branchée ✅ | réutilisée comme store (Forge sait l'appeler) |

**Constat clé** : `/api/health` ne touche pas la DB → il était vert **sans** schéma. Le
fonctionnel, lui, exige le schéma migré, l'auth, et (pour le RAG) Qdrant + le ml-module.

---

## Chantier 0 (fondation) — Schéma DB + auth de service opérationnels

- **Migrations** : appliquer le schéma de Forge sur le Postgres de la brique
  (`briques/forge`). Identifier le mécanisme réel (Alembic ? script d'init ? `setup.sh`)
  et l'exécuter au démarrage de la brique (entrypoint) ou via une cible `make migrate`.
- **Auth de service** : implémenter la voie retenue (S16) dans l'adaptateur :
  obtention/rafraîchissement du jeton (ou injection de l'API key) avant chaque appel protégé.
- **Branchements env déjà prévus côté Forge** : `MEMOIRE_URL`, `GATEWAY_BASE_URL` (faits en
  S15) ; ajouter `KEYCLOAK_URL`/realm si voie Keycloak.

**Critères d'acceptation**
- [ ] Le schéma est présent (tables créées) — vérifié (`\dt` ou endpoint qui lit la DB répond 200).
- [ ] Un appel `GET /api/agents` **via l'adaptateur** (auth de service) renvoie 200 (liste, vide ok).
- [ ] Rejouable sur install fraîche (volume `forge_pgdata` recréé → migrations rejouées).

---

## Chantier 1 — RAG : Qdrant + ml-module dans la brique

> Forge attend `QDRANT_URL` et `ML_MODULE_URL` ; tous deux désactivés en S15.

### Conception
- Ajouter au `briques/forge/docker-compose.yml` : `qdrant` (image `qdrant/qdrant`) et, si
  nécessaire, `ml-module` (build depuis `workspace/forge/ml-module`). Renseigner les env du core.
- **Décision** : embeddings via le **ml-module** de Forge, **ou** réutiliser
  `embedding/all-minilm` de la **Gateway** (déjà utilisé par la brique Mémoire, 384 dims).
  Recommandation : réutiliser la Gateway si Forge le permet (1 moteur d'embeddings pour tout
  Workplace) ; sinon ml-module. Trancher et documenter.

### Critères d'acceptation
- [ ] Qdrant répond (`:6333/healthz`) depuis le conteneur Forge.
- [ ] Un document ingéré crée des vecteurs (collection non vide).

---

## Chantier 2 — Adaptateur : outils d'action Forge (auth)

> Étendre `briques/forge/main.py` (S16) avec le contrat **authentifié**, en français.

### Conception
- `POST /agent/lancer` → proxy authentifié vers la route d'exécution d'agent de Forge
  (réutilise le react_executor de Forge → Gateway 4001). Entrée : objectif + contexte.
- `POST /rag/ingerer` → proxy vers la route documents/ingestion de Forge (→ Qdrant).
- `GET  /rag/chercher?q=` → proxy vers la recherche RAG.
- Mapper les erreurs Forge en messages clairs (auth expirée, schéma absent, Qdrant down).

### Critères d'acceptation
- [ ] `POST :5700/rag/ingerer` (doc de test) → 200 + id ; `GET :5700/rag/chercher?q=…` → passage pertinent.
- [ ] `POST :5700/agent/lancer` (tâche simple) → réponse de l'agent, **modèle = Gateway 4001** (vérifié dans `/assistant/usage` ou logs Gateway).

---

## Chantier 3 — Outils assistant d'action Forge (gardés par confirmation)

> Activer les signatures préparées en S16 dans `core/outils.py` + `core/assistant.py`.

### Conception
- `forge_rag_ingerer` (ACTION, `confirme=true`), `forge_rag_chercher` (lecture),
  `forge_lancer_agent` (ACTION, `confirme=true`) — convention Workplace : lecture libre,
  action confirmée.
- L'assistant explique ce qu'il va faire avant d'agir (effet de bord = écrit dans Forge).

### Critères d'acceptation
- [ ] « cherche X dans Forge » → `forge_rag_chercher` (sans confirmation), réponse juste.
- [ ] « lance un agent qui fait Y » → **confirmation demandée**, puis exécution sur `oui`.
- [ ] Prouvé E2E via `POST /assistant/chat`, pastilles d'outils, 0 stacktrace.

---

## Chantier 4 — Preuve de bout en bout + garde-fous

### Scénario de recette (à rejouer)
1. Ingestion : déposer un document via l'assistant → `forge_rag_ingerer` (confirmé) → Qdrant.
2. Interrogation : « que dit le doc sur Z ? » → `forge_rag_chercher` → passage correct cité.
3. Agent : « résume ce doc et propose 3 actions » → `forge_lancer_agent` (confirmé) →
   réponse cohérente, **coût visible** dans `/assistant/usage` (réutilise S138).
4. Robustesse : couper Qdrant / la Gateway → messages dégradés clairs, pas de crash du Cœur.

### Critères d'acceptation
- [ ] Le scénario 1→3 passe end-to-end depuis le dashboard.
- [ ] La coupure (4) dégrade proprement.
- [ ] Journal `WORKPLACE.md` mis à jour : Forge **🟢 fonctionnel prouvé**.

---

## Séquencement & dépendances

```
Chantier 0 (schéma + auth)  ──►  obligatoire en premier (rien ne marche sans)
        ├─► Chantier 1 (Qdrant/ml-module)  ─ prérequis du RAG
        ├─► Chantier 2 (adaptateur auth: agent + rag)  ─ s'appuie sur 0 (et 1 pour le rag)
        └─► Chantier 3 (outils assistant)  ─ s'appuie sur 2
                └─► Chantier 4 (recette E2E + garde-fous)
```

**Ordre** : `0 → 1 → 2 → 3 → 4`. Le Chantier 0 est le verrou ; tant qu'il n'est pas vert,
ne pas avancer (sinon on empile du code non prouvable).

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S17-1 | Migrations DB Forge appliquées dans la brique (entrypoint / `make migrate`) | 0 | M |
| S17-2 | Auth de service implémentée dans l'adaptateur (voie S16) + refresh | 0 | M |
| S17-3 | `GET /api/agents` 200 via adaptateur (preuve schéma+auth) | 0 | S |
| S17-4 | Qdrant (+ ml-module si retenu) dans le compose + env core | 1 | M |
| S17-5 | Décision embeddings (Gateway all-minilm vs ml-module) + branchement | 1 | S |
| S17-6 | Adaptateur : `POST /rag/ingerer`, `GET /rag/chercher` (auth) | 2 | M |
| S17-7 | Adaptateur : `POST /agent/lancer` (auth, → Gateway) | 2 | M |
| S17-8 | Outils assistant `forge_rag_*` + `forge_lancer_agent` (confirmation) | 3 | M |
| S17-9 | Recette E2E (ingest→search→agent) depuis le dashboard | 4 | M |
| S17-10 | Garde-fous dégradation (Qdrant/Gateway down) + maj WORKPLACE.md | 4 | S |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j.

---

## Métriques de succès du sprint

- **Fonctionnel prouvé** : un agent Forge **et** un cycle RAG tournent **depuis l'assistant**.
- **Branchement Workplace réel** : l'agent consomme la **Gateway** (coût visible `/assistant/usage`) ;
  le RAG utilise un embedder Workplace ; aucune clé LLM en dur dans Forge.
- **Honnêteté** : chaque preuve est un appel réel observé (curl/dashboard), pas « le code existe ».
- **Robustesse** : dégradation propre quand une dépendance tombe.

## Hors-scope (sprint suivant)

- Frontend Forge complet (port 3000) intégré au dashboard Workplace.
- Multi-tenant / E2EE / RGPD avancé de Forge.
- netbird/coturn (VPN) — non requis pour agents/RAG.
- Reprise des autres routers Forge (CRM, ventures, SEO, facturation…) — à prioriser ensuite
  selon la valeur **commerciale** (cf. question : est-ce que ça rapproche d'un euro ?).

---

## Notes d'honnêteté technique

- **C'est le sprint où Forge devient utile — ou pas.** Si à mi-parcours le Chantier 0
  (schéma + auth) résiste plus de ~2 jours, c'est un signal : la dette d'intégration de
  Forge est peut-être supérieure à sa valeur immédiate. Décider alors **explicitement** :
  persévérer, ou geler Forge et réinvestir l'effort sur un produit plus proche de la vente
  (Avocat Digital quand les associés avancent). Ne pas laisser l'inertie décider.
- **Piège connu** : vouloir reprendre « tant qu'on y est » les dizaines d'autres routers de
  Forge (CRM, ventures, SEO…). Frontière dure : S17 = **agents + RAG**, rien d'autre.
- Réutiliser au maximum l'existant Workplace (Gateway, Mémoire, embeddings all-minilm,
  journal d'usage S138) plutôt que de réveiller les sous-systèmes redondants de Forge
  (Qdrant peut être nécessaire ; Keycloak/netbird de Forge ne le sont pas).
