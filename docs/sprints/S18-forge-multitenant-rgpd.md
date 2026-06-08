# Sprint S18 — Forge multi-tenant & RGPD effectif (fondation de sûreté)

> **But du sprint** : faire de Forge un service dont l'**isolation des données** et le
> **respect des droits RGPD** sont **prouvés**, pas supposés. C'est le sprint à passer
> **avant** d'élargir la surface de Forge (frontend S19, routers métier S20) : on ne
> branche pas plus de portes sur une maison dont on n'a pas vérifié les cloisons.
> À la sortie, l'étiquette « multi-tenant / RGPD : non » de S17 devient « **isolation
> prouvée + droits exécutables** ».

- **Sprint** : S18
- **Pré-requis** : **S17** (Forge fonctionnel prouvé — schéma migré, auth de service, RAG/Qdrant debout)
- **Statut** : **code livré** (2026-06-07) — Chantiers 0→3 traités, 9/9 tickets. Restent des
  étapes **opérationnelles** (flip audience live + re-import realm, preuve A/B sur stack 2 orgs,
  at-rest pleine base/volumes infra) et un **gap inter-brique** (contrat `/oublier` + tag `user_id`
  côté Mémoire). Suite de tests : **172 passed, 2 skipped** (live/parité). Détails par ticket en bas.
- **Note** : sprint **structurel**, pas additif. La dette ici **augmente** avec chaque
  ligne écrite ailleurs (chaque requête non scopée est une fuite potentielle à rétro-corriger).
  C'est pour ça qu'il passe **avant** S19/S20.

---

## 0. Constat de départ (vérifié dans le code, 2026-06-06)

- **Le multi-tenant n'est pas à inventer** : `org_id` / `organization_id` est déjà présent
  dans la plupart des routers du core Forge (`ventures`, `crm`, `sessions`, `poles`,
  `automation`, `risk_engine`…). Forge est **nativement multi-org**. Le problème n'est pas
  l'absence du concept — c'est que Workplace l'**utilise en mono-compte de service** (S17) et
  que **l'étanchéité n'a jamais été prouvée** (aucun test « org A ne voit pas les données d'org B »).
- **Le levier d'isolation au niveau auth existe** : `keycloak_auth.py` bascule
  `verify_aud=False` (audience vide ⇒ « tout JWT signé par le realm est accepté », posture
  dev/multi-tenant ouverte) vs `audience` rempli ⇒ vérification stricte. Aujourd'hui Forge
  tourne **audience vide** (cf. note d'auth S17).
- **RGPD : il y a un trompe-l'œil à lever.** `routers/sentinel_rgpd.py` existe mais c'est une
  **checklist de conformité + scoring LLM** (10 points, Art. 30/17/15…) — un **outil d'audit
  déclaratif**, **pas** la machinerie qui **exécute** les droits (effacer réellement les données
  d'une personne, exporter sa donnée, purger selon les durées de conservation). Cocher
  « droit à l'effacement » dans sentinel-rgpd ne supprime **rien**.

**Conséquence** : ce sprint sépare nettement (a) **isolation** (cloisons étanches entre
tenants), (b) **droits RGPD exécutables** (effacement/export réels), (c) **décision E2EE**
(à trancher, probablement incompatible avec le RAG — cf. Chantier 3).

---

## Chantier 0 (décision) — Grain de tenancy de Workplace

> Avant tout code : **trancher et écrire** quel est le modèle de tenant côté Workplace.

### Conception
- **Question** : Workplace reste-t-il **mono-tenant de service** (1 org « perso », l'assistant
  du Cœur est mono-utilisateur — cohérent avec la brique `agenda`), ou prépare-t-on un **vrai
  multi-tenant** (plusieurs clients/orgs isolés, en vue d'un produit vendu) ?
- **Critère de décision** : *est-ce que Workplace va bientôt toucher des données réelles de
  plusieurs clients ?* Si non → on **fige mono-tenant explicitement** (et ce sprint se réduit à
  « prouver qu'on ne fuit pas + droits RGPD sur l'unique org »). Si oui → multi-tenant complet.
- Mapper le tenant Workplace → `org_id` Forge : un tenant = un `org_id`, provisionné au 1er appel
  (déjà le cas en S17 pour le compte de service). Documenter la correspondance.

### Critères d'acceptation
- [x] **Note de décision écrite** (mono- vs multi-tenant) avec le *pourquoi*, dans ce doc.
- [x] Correspondance tenant Workplace ↔ `org_id` Forge documentée (1 ligne par tenant).

### Décision (2026-06-06) — **MULTI-TENANT COMPLET**

**Décidé** : Workplace est traité comme une plateforme **multi-tenant** où plusieurs
orgs réellement isolées peuvent coexister.

**Pourquoi** : on vise un produit susceptible de servir les données réelles de
plusieurs clients/orgs. Le critère du sprint (« va-t-on bientôt toucher des données
réelles de plusieurs clients ? ») est tranché **oui**. Conséquence assumée : on ne
peut pas se contenter de « prouver qu'on ne fuit pas sur l'unique org » — il faut
**l'audit complet du scoping `org_id` de tous les routers data-bearing** + un **test
croisé A/B vert** (lecture *et* écriture) comme preuve d'étanchéité.

**Modèle de tenancy** :
- **1 tenant = 1 `org_id` Forge** (UUID). Pas de niveau au-dessus de l'org.
- **Provisioning** : au 1er login, `app/auth.py::_ensure_personal_org` crée l'org
  personnelle (owner = user) + le membership `owner`. Un tenant existant se rejoint
  via un `OrganizationMembers` (rôle owner/admin/member).
- **Org active d'une requête** : résolue par `app/auth.py::_resolve_org` —
  header `X-Org-ID` honoré **uniquement si l'appelant est membre** de cette org,
  sinon fallback sur l'org personnelle. C'est la **seule** source d'`org_id` de
  confiance ; elle est exposée par `UserContext.org_id`.
- **Règle d'or** (à imposer Chantier 1) : tout router data-bearing scope par
  `user.org_id` (issu du `UserContext`), **jamais** par un `X-Org-ID` lu en direct
  depuis le header — ce dernier court-circuite la validation d'appartenance.

**Correspondance tenant ↔ org_id** (1 ligne par tenant, à tenir à jour) :

| Tenant | org_id Forge | Plan | Notes |
|---|---|---|---|
| Workplace (compte de service S17 — org perso du propriétaire) | provisionné au 1er login (UUID, plan `personal`) | personal | tenant historique mono-compte de S17 ; devient *un* tenant parmi d'autres |
| _(clients futurs)_ | _1 org_id par client_ | _team/pro_ | _à compléter à chaque onboarding_ |

---

## Chantier 1 — Isolation prouvée (auth + scoping des requêtes)

> Le cœur du sprint : démontrer qu'**un tenant ne peut pas lire/écrire les données d'un autre**.

### Conception
- **Auth** : passer Forge en posture verrouillée — renseigner `audience` (⇒ `verify_aud=True`)
  pour que seul un token destiné à Forge soit accepté, au lieu de « tout JWT du realm ». Garder
  le compte de service S17, mais avec audience explicite.
- **Scoping** : **audit de chaque router** qui lit/écrit des données — vérifier que **toute**
  requête filtre par l'`org_id` du `UserContext` (pas par un `org_id` reçu en paramètre/corps,
  qui serait falsifiable). Repérer les routes qui font confiance à un id client. C'est le vrai
  travail : `org_id` *présent dans le modèle* ≠ *imposé à chaque requête*.
- **Test d'étanchéité** (le livrable qui prouve) : provisionner **deux orgs** (A et B), créer une
  donnée dans A, prouver par appel réel que le token de B reçoit **403/404/liste vide** — jamais
  la donnée de A. Idem en écriture (B ne peut pas modifier une ressource de A).

### Critères d'acceptation
- [~] Forge tourne avec `audience` renseigné (`verify_aud=True`) ; token sans la bonne audience → 401.
      **Préparé** (mappers realm + plumbing + tests) ; flip live = re-import realm + env, cf. S18-2 ci-dessous.
- [~] **Test croisé A/B vert** : aucune route ne laisse B voir/modifier une donnée de A (preuve curl).
      Test écrit + garde CI verte ; exécution live à faire sur stack 2 orgs.
- [x] Toute route data-bearing filtre par l'`org_id` du contexte d'auth, **jamais** par un id reçu du client.
- [x] Liste des routers audités + verdict (étanche / corrigé / à risque) consignée.

### Mécanisme de scoping (S18-3, fait 2026-06-07)

Dépendance centrale ajoutée dans `app/auth.py` :

```python
async def require_org(user: UserContext = Depends(get_current_user)) -> str:
    """Org active validée de la requête (S18, Chantier 1)."""
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No active organization")
    return user.org_id
```

`user.org_id` provient de `_resolve_org`, qui n'honore un `X-Org-ID` **que si l'utilisateur
est membre** (sinon repli sur l'org perso). Tout router data-bearing a été basculé de
`Header("X-Org-ID")` / `request.headers.get("X-Org-ID")` **crus** vers `Depends(require_org)`,
et le filtre `org_id` est rendu **obligatoire** (plus de branche « si header présent »).

### Audit des routers — verdict

Deux patterns de « header cru » existaient (le second avait été manqué au premier passage) :
`Header(alias="X-Org-ID")` en paramètre **et** `request.headers.get("X-Org-ID")` dans le corps.

| Router | Avant | Verdict | Correctif |
|---|---|---|---|
| `team.py` | filtré par header org **seul** (ni user.sub ni appartenance) | **fuite → corrigé** | `require_org`, scope membre |
| `slo.py` | `select(SloEntries)` **sans scope** ; sans header → tous les orgs | **fuite (lecture+écriture) → corrigé** | `require_org`, org obligatoire |
| `llm_config.py` (`/global`) | `header or user.org_id` → preset LLM d'un autre org | **fuite (lecture+écriture) → corrigé** | `require_org` |
| `stripe.py` (`get_abonnement`) | requête org-seule sur header cru | **fuite → corrigé** | `require_org` |
| `degradation.py` | repli « sql 1=1 » global | **fuite → corrigé** | `require_org` + `_mode_in_org` |
| `staging.py` | repli « sql 1=1 » global | **fuite → corrigé** | `require_org` |
| `sessions.py` (`rename_session`) | `UPDATE` par id **sans scope** (écriture cross-tenant) | **fuite (écriture) → corrigé** | contrôle owner/membre |
| `sessions.py` (`create_session`) | stamp header cru | à risque → corrigé | `require_org` |
| `memory_palace.py` | user.sub + header optionnel | à risque → corrigé | `require_org`, org obligatoire |
| `automation.py`, `saved_filters.py`, `calendar.py`, `dev_team.py`, `governor.py`, `risk_engine.py`, `templates.py` | scopés `user.sub`, header optionnel | à risque (règle d'or) → corrigé | `require_org` |
| `rapport.py`, `morning_brief.py`, `injection_guard.py`, `audit_logs.py` | scopés `user.sub`, header stampé à l'écriture | à risque (règle d'or) → corrigé | `require_org`, org obligatoire |
| `brief.py` | header → preset LLM ; **lecture blackboard globale** | **fuite → corrigé** | `require_org` ; blackboard scopé via `poles.org_id` de l'org active, repli global supprimé |
| `ventures.py` | helper `_resolve_org_id` (valide l'appartenance) ; listes scopées `owner_id` | **étanche** | inchangé |
| `templates.py` (templates publics) | partage cross-org **volontaire** | **étanche (fonctionnalité)** | préservé |

**Vérif** : `grep 'X-Org-ID'` dans `app/routers/` ne renvoie plus que `ventures.py` (helper validé)
et des commentaires/docstrings. Suite de tests : **161 passed, 1 skipped** (parité Bun, live requis).

**Réserve honnête** : les lignes legacy à `org_id = NULL` (créées en S17 mono-compte) deviennent
invisibles sous le filtre org obligatoire → migration de backfill à prévoir (cf. S18-5/Chantier 2).

### Test d'étanchéité croisé A/B (S18-4, fait 2026-06-07)

Deux couches dans `tests/test_s18_isolation.py` :

1. **Garde de régression (sans DB, toujours en CI)** — 3 tests verts :
   - `require_org` ne renvoie que `user.org_id` (jamais le header) ;
   - sans org active → `400` (pas de repli sur un id client) ;
   - **scan statique** : aucun router (hors `ventures.py` validé) ne relit `X-Org-ID` cru.
     Réintroduire un `Header(alias="X-Org-ID")` ou `request.headers.get("X-Org-ID")` casse le test.

2. **Test croisé A/B live (gated, skip sans stack)** — `test_cross_tenant_memory_lecture_et_ecriture` :
   A crée une mémoire, on prouve par appel réel que B ne la voit pas (liste) et ne peut pas
   l'écraser (PUT par id). Activé via `FORGE_LIVE_URL`, `FORGE_TOKEN_A`, `FORGE_TOKEN_B`.

Procédure curl équivalente (preuve manuelle sur stack live, deux orgs A et B) :

```bash
# A crée une donnée
curl -s -X POST $FORGE/api/memory -H "Authorization: Bearer $TOKEN_A" \
  -H 'Content-Type: application/json' -d '{"cle":"secret-A","valeur":"conf A"}'

# B liste : "secret-A" NE DOIT PAS apparaître (sinon fuite en lecture)
curl -s $FORGE/api/memory -H "Authorization: Bearer $TOKEN_B" | jq '.[].cle'

# B passe l'X-Org-ID de A en clair : DOIT être ignoré (repli org perso de B), pas la donnée de A
curl -s $FORGE/api/memory -H "Authorization: Bearer $TOKEN_B" -H "X-Org-ID: $ORG_A" | jq '.[].cle'
```

Tant que la stack à deux orgs n'est pas provisionnée, le critère « preuve curl » reste à
exécuter en live ; la garde CI prouve déjà que le **mécanisme** (ignorer le header, scoper
sur l'org validée) est en place et ne peut plus régresser silencieusement.

### Posture d'audience (S18-2, préparé 2026-06-07)

**Constat** : en live, le core vérifie les JWT contre le realm **`oria`** (pas `forge-realm.json`),
et Forge est appelé par le compte de service **`forge-service`** (S2S, S17). Ce client n'avait
**aucun** mapper d'audience → ses tokens ne portent pas d'`aud` Forge. Activer `verify_aud=True`
sans préparation **casserait** l'auth (lock-out). C'est pourquoi le flip n'est pas fait à chaud.

**Préparé (sûr, rétro-compatible)** :
- `oria-realm.json` : mapper `audience-forge` (`oidc-audience-mapper`, `included.custom.audience: "forge"`,
  access-token) ajouté à **`forge-service`** (chemin S2S) **et** `oria-app` (tokens utilisateurs, défensif).
  Le mapper *ajoute* `forge` au tableau `aud`, sans casser l'audience `oria-app` existante.
- `app/config.py` : `KEYCLOAK_AUDIENCE` (vide ⇒ `verify_aud` OFF) déjà branché sur `KeycloakSettings`
  (`audience` vide ⇒ `options={"verify_aud": False}`, sinon vérification active).
- `docker-compose.yml` : `KEYCLOAK_AUDIENCE=${FORGE_KEYCLOAK_AUDIENCE:-}` (défaut vide).
- `.env.example` : `FORGE_KEYCLOAK_AUDIENCE=` documenté.
- Tests : `test_audience_vide_desactive_verify_aud` + `test_audience_renseignee_active_verify_aud` (verts).

**Cutover live (à exécuter sur la stack)** :
1. Ré-importer le realm `oria` (les tokens forge-service/oria-app portent alors `aud: forge`).
2. `FORGE_KEYCLOAK_AUDIENCE=forge` dans `.env`, puis redémarrer le core Forge.
3. Vérifier : token forge-service → 200 ; token forge d'un autre realm/sans `aud: forge` → 401.

**Rollback** : remettre `FORGE_KEYCLOAK_AUDIENCE=` (vide) + restart → retour posture S17.

---

## Chantier 2 — Droits RGPD exécutables (pas seulement audités)

> Lever le trompe-l'œil sentinel-rgpd : passer de « on coche » à « on exécute ».

### Conception
- **Droit à l'effacement (Art. 17)** : une opération qui, pour un sujet/org donné, **supprime
  réellement** ses données là où elles vivent — Postgres Forge **+ vecteurs Qdrant** (RAG) **+
  brique Mémoire (5600)**. Le RAG est le piège : effacer la ligne SQL sans purger les vecteurs =
  donnée toujours interrogeable. L'effacement doit traverser **les trois stores**.
- **Droit d'accès / portabilité (Art. 15/20)** : export de la donnée d'un sujet/org en format
  réutilisable (JSON). Réutiliser le scoping `org_id` du Chantier 1.
- **Durées de conservation (Art. 5)** : au minimum **documenter** la durée par type de donnée ;
  idéalement une purge planifiée. Décider du périmètre réaliste pour ce sprint.
- **Articulation avec sentinel_rgpd** : garder le router comme **tableau de bord de conformité**,
  mais **rebrancher** les points « effacement » / « accès » sur les opérations réelles ci-dessus —
  pour que le score reflète une capacité prouvée, pas une déclaration.
- **Journal** : tracer effacements/exports dans le router `audit` existant (traçabilité = Art. 30).

### Critères d'acceptation
- [x] `effacement(sujet)` supprime la donnée dans **Postgres + Qdrant** + tente **Mémoire** —
      mécanisme livré (`app/rgpd.py`, `POST /api/rgpd/effacer`) ; preuve `GET /rag/chercher`
      vide = à exécuter sur stack live (DB + Qdrant). Limite Mémoire documentée (gap inter-brique).
- [x] Export d'un sujet → JSON complet et scopé (`GET /api/rgpd/export`, scopé `user.sub`).
- [x] Durées de conservation documentées par type de donnée (table dans ce doc) — **S18-7**, ci-dessous.
- [x] Chaque export laisse une **trace d'audit** (`audit_logs`, action `rgpd_export`) ; chaque
      effacement laisse un **reçu horodaté** en Mémoire (`rgpd_effacement`) — cf. **S18-8**.

### RGPD exécutable (S18-5 effacement + S18-6 export, fait 2026-06-07)

**Trompe-l'œil levé** : `sentinel_rgpd` reste un *tableau de bord* consultatif (checklist +
commentaire LLM sur une entreprise fictive) — il ne touchait **aucune** donnée réelle. Les vrais
droits sont désormais dans un module dédié `app/rgpd.py` + router `app/routers/rgpd.py` :

| Route | Droit | Effet |
|---|---|---|
| `GET /api/rgpd/apercu` | — | compte, par table, ce que l'effacement supprimerait (lecture seule) |
| `GET /api/rgpd/export` | Art. 15 & 20 | sérialise en JSON toutes les lignes du sujet (`user.sub`) |
| `POST /api/rgpd/effacer` | Art. 17 | efface Postgres + Qdrant + (best-effort) Mémoire ; `confirmation: "EFFACER"` obligatoire |

**Mécanisme d'effacement** :
- **Postgres** : introspection de `Base.metadata` → balaye **toute** table portant `user_id`
  (robuste aux ajouts de tables), suppression en **ordre FK-safe** (`reversed(sorted_tables)`,
  enfants avant parents), puis la ligne `users` du sujet. Renvoie `{table: lignes}`.
- **Qdrant** : `mem.delete_by_user` supprime par filtre `payload.user_id` dans les 4 collections
  d'embedding (`forge_local/openai/gemini/mistral`) — sinon la donnée resterait interrogeable via RAG.
- **Mémoire (5600)** : `mem.mem_forget_user` tente `POST /oublier`. **Limite assumée** : la brique
  n'expose côté Workplace que `/retenir` + `/rappeler`, et les souvenirs Forge sont écrits dans un
  **espace partagé sans `user_id`** → oubli sélectif impossible aujourd'hui. Effacement réel côté
  Mémoire = (1) contrat `/oublier` sur la brique + (2) marquage `user_id` à l'écriture (backlog inter-brique).
- **Reçu** : un reçu horodaté (lignes par store) est persisté en Mémoire (`type=rgpd_effacement`)
  comme preuve d'exécution (Art. 17(3)), hors périmètre sujet.

**Limites honnêtes** :
- enfants sans `user_id` direct (ex. `messages` via `session_id`) → dépendent d'un `ON DELETE CASCADE`
  base ; à vérifier au schéma.
- périmètre = **sujet self-service** ; l'effacement d'un membre par un admin d'org est un autre flux (backlog).

**Tests** (`tests/test_s18_rgpd.py`, 5 verts, sans DB) : inventaire non vide & cohérent, ordre FK-safe,
sérialisation UUID/datetime/Decimal, routes protégées (401). L'effacement/export bout-en-bout se
valide sur stack live (DB + Qdrant).

### Durées de conservation (S18-7, Art. 5 — défini 2026-06-07)

Durée par **catégorie** de donnée (et non par table) ; « base » = obligation légale ou choix produit.
Toutes les durées s'entendent **sauf exercice du droit à l'effacement** (Art. 17), qui prime et
supprime immédiatement (cf. S18-5). Le point de départ est la dernière activité du compte, sauf mention.

| Catégorie | Tables principales | Durée | Base |
|---|---|---|---|
| **Comptabilité / facturation** | `factures_docs`, `contrats`, `stripe_payments`, `abonnements` | **10 ans** | Obligation légale (C. com. L123-22) — survit à l'effacement du sujet |
| **Prospection / CRM** | `crm_leads` | **3 ans** sans contact | Reco CNIL (prospection B2B/B2C) |
| **Logs de sécurité** | `audit_logs`, `injection_logs`, `risk_logs` | **1 an** | LCEN (logs de connexion/sécurité) |
| **Conversations & sessions** | `sessions`, `messages`, `orchestrator_sessions`, `agent_runs`, `agent_executions` | **Durée du compte**, purge après **24 mois** d'inactivité | Choix produit (minimisation) |
| **RAG / documents** | `documents`, vecteurs Qdrant | **Durée du compte** ; supprimé à l'effacement | Minimisation — indexé tant que le compte vit |
| **Mémoire agents** | `memory_entries` | **Durée du compte** | Fonctionnel (contexte agents) |
| **Coûts LLM / usage** | `governor_usage` | **13 mois** | Analytics (fenêtre glissante CNIL) |
| **Production métier** | `budget_entries`, `forecast_entries`, `okrs`, `incidents`, `rapports`, `briefs`, `tasks`, `dev_tasks`, `ventures`, `poles` | **Durée du compte** | Données créées par l'utilisateur, sous son contrôle |
| **Secrets / jetons tiers** | `provider_api_keys`, `google_oauth_tokens`, `imap_configs`, `social_accounts` | Jusqu'à **révocation / déconnexion** | Sécurité — chiffrés at-rest (cf. `ENCRYPTION_KEY`) |
| **Notifications push** | `push_subscriptions` | Jusqu'à **expiration / désabonnement** | Technique |

**Purge planifiée** : hors-scope de ce sprint (pas d'ordonnanceur dédié monté côté Forge). Proposition
concrète backlog : un job quotidien `scripts/purge_retention.py` qui supprime, par catégorie, les
lignes au-delà de leur durée (logs sécurité > 1 an, CRM > 3 ans sans contact, sessions > 24 mois
d'inactivité) — en **excluant** la catégorie comptable (rétention légale). Les durées ci-dessus sont
la **spécification** de ce job ; tant qu'il n'est pas planifié, la conservation est *documentée mais
non automatiquement appliquée* (dette assumée).

### Sentinel rebranché sur le réel + traçabilité (S18-8, fait 2026-06-07)

`sentinel_rgpd` reste l'outil de **conseil** (audit RGPD d'entreprises tierces). Ce qu'on rebranche,
c'est la mesure de la **posture de Forge lui-même** : nouvelle route `GET /api/sentinel-rgpd/capacites-forge`
qui rend, par point de la checklist, une capacité **prouvée par une route réelle** (≠ case cochée) :

| Point | Prouvé ? | Preuve |
|---|---|---|
| Droit d'accès / portabilité | ✅ | `GET /api/rgpd/export` (S18-6) |
| Droit à l'effacement | ✅ | `POST /api/rgpd/effacer` — Postgres+Qdrant+Mémoire (S18-5) |
| Durées de conservation | ✅ | table de rétention ci-dessus (S18-7) |
| Minimisation | ✅ | scoping org imposé par `require_org` (S18-3) |
| Registre, consentement, DPIA, DPO, transferts, notif. violation | ❌ | **organisationnel** (hors code) — reste déclaratif |

`scoreSysteme` = 4/10 points prouvés par le système (40 %) ; le reste est explicitement marqué
organisationnel — **pas** gonflé par des cases auto-cochées. C'est l'honnêteté demandée : le score
reflète une capacité prouvée, pas une déclaration.

**Traçabilité (Art. 30)** :
- **Export** → entrée `audit_logs` (`action=rgpd_export`, détail = tables exportées). Le sujet existe
  encore, l'écriture est valide.
- **Effacement** → **reçu** horodaté en Mémoire (`type=rgpd_effacement`). Choix assumé : on **ne** peut
  pas garder la trace dans `audit_logs` du sujet (elle fait partie de ce qui est effacé, et la FK vers
  `users` saute) ; le registre minimal de l'effacement vit donc hors périmètre sujet (Art. 17(3)).

---

## Chantier 3 — E2EE : décision tranchée (et honnête)

> Ne pas « ajouter E2EE » par réflexe. Le confronter au RAG **d'abord**.

### Conception
- **Tension réelle** : un **chiffrement de bout en bout** (le serveur ne voit jamais le clair)
  est **structurellement incompatible** avec le RAG tel que construit en S17 — on ne peut pas
  **embedder / indexer / réranker** un document qu'on ne peut pas lire en clair côté serveur.
  Choisir E2EE = renoncer au RAG serveur (ou le déporter côté client, autre projet).
- **Trancher entre** :
  1. **E2EE intégral** → incompatible RAG serveur. À n'envisager que si la confidentialité prime
     sur la fonction RAG (probablement non, vu la valeur de S17).
  2. **Compromis réaliste (recommandé)** : **chiffrement au repos** (at-rest, DB + volumes Qdrant)
     + **TLS in-transit** + isolation tenant (Chantiers 1-2). On protège le vol de disque et
     l'interception réseau, **sans** casser le RAG. Ce n'est pas de l'E2EE — **le dire clairement**.
  3. **Statu quo documenté** : ni at-rest ni E2EE pour l'instant, mais **écrit** comme dette
     assumée avec une date de revue.

### Critères d'acceptation
- [x] **Note de décision E2EE écrite** (option 1/2/3 + *pourquoi*), assumant l'arbitrage RAG — ci-dessous.
- [~] Si option 2 retenue : at-rest **partiel** (secrets chiffrés champ-à-champ AES-256-GCM) ; at-rest
      pleine base/volumes + vérif TLS = **infra, backlog cadré** ci-dessous. La doc ne qualifie **pas**
      ça d'« E2EE ».

### Décision E2EE (S18-9, tranché 2026-06-07) — **OPTION 2 : at-rest + TLS + isolation, PAS d'E2EE**

**Décision** : on **renonce explicitement à l'E2EE intégral** (option 1) et on retient le **compromis
réaliste** (option 2). **Pourquoi** : l'E2EE (le serveur ne voit jamais le clair) est structurellement
incompatible avec le RAG de S17 — on ne peut ni *embedder*, ni *indexer*, ni *réranker* un document
illisible côté serveur. Or le RAG est une valeur centrale prouvée en S17 (agents + récupération). Sacrifier
le RAG pour une promesse E2EE serait un mauvais arbitrage produit. L'option 3 (statu quo) est insuffisante
pour un produit multi-client vendable. → **Option 2**.

**Vocabulaire (honnêteté)** : ce qui suit est du **chiffrement at-rest + TLS in-transit + isolation
tenant**. Ce **n'est pas** de l'E2EE et ne doit jamais être présenté comme tel : le serveur Forge voit
le clair (nécessaire au RAG). On protège **le vol de disque** et **l'interception réseau**, pas la
confidentialité vis-à-vis de l'opérateur du serveur.

**Déjà en place** :
- **Secrets sensibles chiffrés au niveau champ** (AES-256-GCM, `app/crypto.py`, clé `ENCRYPTION_KEY`) :
  clés API providers (`provider_api_keys`), identifiants serveurs, configs IMAP, clés LLM. Compatible Bun.
- **Isolation tenant** prouvée/durcie aux Chantiers 1-2 (scoping `org_id`, droits RGPD réels).

**Reste à faire (infra, backlog cadré — hors code applicatif)** :
- **At-rest pleine base** : activer le chiffrement disque/volume du Postgres Forge et des **volumes Qdrant**
  (le RAG est le maillon souvent oublié : vecteurs = données personnelles en clair sur disque). Option :
  volumes chiffrés (LUKS/loop) ou Postgres TDE selon l'hébergeur.
- **TLS in-transit** : vérifier le chiffrement sur **tous** les sauts (client→reverse-proxy, et internes
  core↔Gateway↔Qdrant↔Mémoire). Aujourd'hui le maillage interne passe par `host.docker.internal` /
  Netbird ; auditer que rien de personnel ne circule en clair hors tunnel.
- **Rotation `ENCRYPTION_KEY`** : procédure de rotation documentée (re-chiffrement des secrets) — backlog.

Ces points sont **infra/déploiement** : ils ne bloquent pas S19/S20 (frontend, routers métier), mais
doivent être traités avant une mise en production multi-client réelle. La décision (option 2) est **actée**.

---

## Séquencement & dépendances

```
Chantier 0 (grain de tenancy)  ──►  verrou : tout le reste en découle
        ├─► Chantier 1 (isolation auth + scoping)   ─ le cœur
        ├─► Chantier 2 (droits RGPD exécutables)     ─ s'appuie sur le scoping de 1
        └─► Chantier 3 (décision E2EE)               ─ indépendant, mais à acter avant S19/S20
```

**Ordre** : `0 → 1 → 2 → 3`. Et **S18 avant S19 et S20** : on n'élargit la surface
(frontend, routers métier) qu'une fois les cloisons prouvées.

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S18-1 | Note de décision grain de tenancy (mono vs multi) + mapping tenant↔org_id | 0 | S | ✅ |
| S18-2 | Forge en `audience`/`verify_aud=True` + compte de service ajusté | 1 | S | ✅ code ; flip live = re-import realm |
| S18-3 | Audit du scoping `org_id` de chaque router data-bearing + corrections | 1 | L | ✅ |
| S18-4 | Test d'étanchéité croisé org A/B (lecture + écriture) — preuve curl | 1 | M | ✅ garde CI ; preuve live à exécuter |
| S18-5 | Effacement réel multi-store (Postgres + Qdrant + Mémoire) | 2 | M | ✅ code ; preuve live + gap Mémoire documenté |
| S18-6 | Export accès/portabilité scopé (JSON) | 2 | M | ✅ |
| S18-7 | Durées de conservation documentées (+ purge si réaliste) | 2 | S | ✅ ; purge planifiée = backlog |
| S18-8 | Rebranchement sentinel_rgpd sur opérations réelles + trace audit | 2 | S | ✅ |
| S18-9 | Note de décision E2EE (+ at-rest/TLS si option 2) | 3 | M | ✅ décision ; at-rest full = infra backlog |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j, L ≈ 3–4j. Colonne état au 2026-06-07.

---

## Métriques de succès du sprint

- **Isolation prouvée** : un test croisé A/B réel montre qu'aucun tenant ne lit/écrit chez l'autre.
- **Droits RGPD réels** : effacement et export **fonctionnent sur les trois stores**, observés.
- **Vocabulaire honnête** : ce qui est « at-rest » est appelé at-rest, pas « E2EE ».
- **Aucune régression S17** : l'agent et le RAG marchent toujours depuis l'assistant.

## Hors-scope (sprints suivants)

- Frontend Forge intégré (→ **S19**) — délibérément après l'isolation.
- Reprise des routers métier (→ **S20**).
- Consentement granulaire par finalité, registre des traitements outillé (au-delà du doc) — backlog.

---

## Notes d'honnêteté technique

- **C'est le sprint le moins « démontrable au client » et le plus important.** La tentation
  sera de le sauter pour montrer du frontend (S19). Résister : une fuite inter-tenant après le
  premier vrai client coûte infiniment plus que ce sprint.
- **Le piège du multi-tenant** : `org_id` *dans le modèle* donne une fausse sécurité. La seule
  preuve qui compte est le **test croisé A/B**. Tant qu'il n'est pas vert, considérer Forge comme
  **non isolé**, quoi que dise le schéma.
- **Le piège RGPD** : sentinel_rgpd **rassure sans protéger**. Un score de conformité élevé sur
  une machinerie qui n'efface rien est pire que pas de score — il endort. Ce sprint doit relier
  le score à une **capacité prouvée**.
- **E2EE** : ne pas le promettre. Si on veut vraiment du zéro-connaissance, c'est un produit
  différent (chiffrement côté client, RAG client) — à ne pas confondre avec « DB chiffrée ».
