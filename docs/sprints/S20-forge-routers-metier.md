# Sprint S20 — Reprise des routers métier de Forge (par valeur commerciale)

> **But du sprint** : rebrancher, **un par un et par ordre de valeur**, les fonctions métier de
> Forge (CRM, ventures, facturation, SEO, contrats, légal…) comme **outils réels** de Workplace,
> sous les cloisons S18 et derrière l'UI S19. **Pas « tout reprendre »** : reprendre ce qui
> **rapproche d'un euro**, prouver, puis décider du suivant.

- **Sprint** : S20
- **Pré-requis** : **S18** (isolation prouvée) **et** **S19** (UI intégrée, SSO)
- **Statut** : **réalisé — `facturation` (n°1) ET `crm` (n°2) branchés et prouvés E2E** (2026-06-07)
  Chantier 1 vert (`facturation` : lecture + 3 actions). Chantier 2 vert (`crm` : lecture + 2 actions,
  avec résolution de pôle amorcée). Détails en fin de doc (« Réalisé »).
- **Note** : sprint **itératif et priorisé**. Le risque n'est pas technique (le motif adaptateur
  de S17 se répète) — c'est la **dispersion**. Frontière dure : 1–2 routers à forte valeur, prouvés
  bout-en-bout, plutôt que dix à moitié.

---

## 0. Constat de départ (vérifié dans le code, 2026-06-06)

- Le core Forge expose **des dizaines de routers** déjà écrits : `crm`, `ventures`,
  `facturation`, `seo_agent`, `social`, `contrats`, `legal_agent`, `okr`, `budget`, `forecast`,
  `automation`, `risk_engine`, `audit`, `deploy`… La valeur de code existe ; ce qui manque, c'est
  le **branchement prouvé** dans Workplace (comme agents/RAG en S17).
- Le **motif est connu** (S17) : pour chaque fonction → route d'adaptateur authentifiée
  (`briques/forge/main.py`) + outil assistant (lecture libre / action confirmée) + preuve E2E.
- La plupart de ces routers portent déjà `org_id` ⇒ **ils héritent des cloisons S18** dès lors
  que le scoping a été audité (S18-3). **Ne reprendre que des routers déclarés étanches en S18.**

---

## Chantier 0 (décision) — Prioriser par l'euro

> Le livrable le plus important du sprint : **choisir quoi brancher**, pas tout.

### Conception
- Pour chaque router candidat, répondre à **une** question : *est-ce que le brancher rapproche
  d'un euro ?* (vente, facturation, acquisition client, réduction de coût réel).
- **Hypothèses de tête de liste** (à confirmer avec la réalité business) :
  - **`facturation` / `stripe`** : touche directement l'encaissement → candidat n°1 plausible.
  - **`crm`** : suivi prospects/clients → proche de la vente.
  - **`contrats` / `legal_agent`** : si l'activité juridique (Avocat Digital) avance, forte valeur.
  - **`ventures` / `okr` / `forecast`** : pilotage interne — valeur réelle mais **indirecte**, à
    repousser sauf besoin précis.
- **Garde-fou** : aucun router branché « tant qu'on y est ». Chaque reprise est un choix justifié.

### Critères d'acceptation
- [ ] **Liste priorisée écrite** (router → valeur euro → décision : reprendre / repousser / abandonner).
- [ ] **1 à 2 routers** retenus pour ce sprint, le reste explicitement repoussé (backlog daté).

---

## Chantier 1 — Reprise du router prioritaire n°1 (motif S17)

> Appliquer le motif adaptateur éprouvé en S17 au premier router retenu.

### Conception
- Vérifier qu'il a été **déclaré étanche en S18** (sinon, l'auditer d'abord — bloquant).
- Adaptateur (`briques/forge/main.py`) : routes authentifiées (auth de service S17/S18) en
  **français**, mappant les erreurs Forge en messages clairs.
- Outils assistant (`core/outils.py` + `core/assistant.py`) : **lecture libre**, **action
  confirmée** (convention Workplace). L'assistant explique l'effet de bord avant d'agir.
- Si une UI existe pour ce router dans la SPA (S19) : la **dé-masquer** (elle était grisée en S19).

### Critères d'acceptation
- [ ] Lecture E2E depuis l'assistant (ex : « liste mes factures impayées ») → réponse juste, scopée tenant.
- [ ] Action E2E confirmée (ex : « crée une facture pour X ») → effet réel + **coût Gateway visible** (`/assistant/usage`).
- [ ] Étanchéité re-vérifiée pour CE router (tenant A ne touche pas B).
- [ ] Dégradation propre si le router/DB tombe (pas de crash du Cœur).

---

## Chantier 2 — Reprise du router prioritaire n°2 (si capacité)

> Même motif, deuxième fonction — **uniquement** si le Chantier 1 est vert et qu'il reste du temps.

### Critères d'acceptation
- [ ] Mêmes critères que Chantier 1, appliqués au 2ᵉ router.
- [ ] **Stop discipline** : si le Chantier 1 a débordé, ce chantier passe en backlog **sans culpabilité**.

---

## Chantier 3 — Bilan & ré-arbitrage

### Conception
- Mesurer : les fonctions branchées **servent-elles vraiment** (usage réel, pas démo) ?
- Ré-évaluer le reste du backlog Forge à la lumière de l'effort réel constaté ici.

### Critères d'acceptation
- [ ] Bilan écrit : routers branchés, usage observé, coût d'intégration réel vs valeur.
- [ ] Backlog des routers restants **réordonné** (ou **gelé** si la valeur ne se confirme pas).
- [ ] Journal `WORKPLACE.md` mis à jour (fonctions métier branchées, état).

---

## Séquencement & dépendances

```
Chantier 0 (prioriser par l'euro)  ──►  verrou : décide tout le sprint
        └─► Chantier 1 (router n°1, motif S17)
                └─► Chantier 2 (router n°2, si capacité)
                        └─► Chantier 3 (bilan + ré-arbitrage)
```

**Ordre** : `0 → 1 → (2) → 3`. Et **S20 après S18 + S19**.

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S20-1 | Liste priorisée des routers (valeur euro) + choix 1–2 pour le sprint | 0 | S |
| S20-2 | Vérif étanchéité S18 du router n°1 (bloquant) | 1 | S |
| S20-3 | Adaptateur authentifié router n°1 (français, erreurs claires) | 1 | M |
| S20-4 | Outils assistant router n°1 (lecture libre / action confirmée) | 1 | M |
| S20-5 | Preuve E2E lecture + action (coût Gateway visible) + dé-masquage UI | 1 | M |
| S20-6 | (si capacité) Router n°2 : adaptateur + outils + preuve E2E | 2 | M |
| S20-7 | Bilan usage réel + ré-arbitrage backlog + maj WORKPLACE.md | 3 | S |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j.

---

## Métriques de succès du sprint

- **Valeur, pas couverture** : 1–2 fonctions **réellement utilisées**, prouvées E2E, scopées tenant.
- **Discipline de périmètre** : le reste reste explicitement au backlog — aucun router « à moitié branché ».
- **Branchement Workplace réel** : Gateway pour le LLM (coût visible), cloisons S18 respectées.

## Hors-scope

- Reprise exhaustive de tous les routers Forge — **anti-objectif** de ce sprint.
- Nouvelles fonctions métier (au-delà de ce que Forge a déjà) — autre projet.

---

## Réalisé (2026-06-07)

### Chantier 0 — Décision de priorisation (l'euro)

Liste priorisée des routers candidats. **Critère unique : ça rapproche d'un euro ?**

| Router | Valeur euro | Décision |
|---|---|---|
| **`facturation`** | **Encaissement direct** : devis → facture → paiement. Le plus court chemin vers l'euro. | **✅ Repris (n°1)** |
| **`crm`** | **Suivi prospects/clients + pipeline** (en amont de l'euro, alimente la facturation) | **✅ Repris (n°2)** |
| `stripe` | Paiement en ligne réel — fort, mais dépend de clés/compte Stripe configurés (dépendance externe) | Repoussé (après `facturation`) |
| `contrats` / `legal_agent` | Valeur si l'activité juridique avance — pas le besoin immédiat | Repoussé |
| `ventures` / `okr` / `forecast` / `budget` | Pilotage interne — valeur **indirecte** | Gelé (pas dans ce cycle) |
| `seo_agent` / `social` / `content_agent` | Acquisition — valeur réelle mais diffuse | Repoussé |

**Choix du sprint : 2 routers (`facturation` puis `crm`).** `facturation` (encaissement) en
n°1 ; `crm` (prospects/pipeline) en n°2 car il **alimente** la facturation — un prospect
gagné devient un devis puis une facture, bouclant la chaîne commerciale. Le reste du backlog
reste explicitement repoussé/gelé (discipline de périmètre tenue).

### Chantier 1 — `facturation` (motif S17)

**Étanchéité (bloquant, vérifié).** `facturation` scope par **`user.sub`** (l'utilisateur
Forge), **pas** par `org_id` — il n'est donc pas concerné par le mécanisme `X-Org-ID`
audité en S18. Or l'adaptateur appelle le core avec **un token de service unique**
(`forge-service`, `client_credentials`) ⇒ **toutes** les requêtes Workplace tombent sur
**une seule identité Forge**. Conséquence honnête :
- ✅ **Pas de fuite inter-tenant** au niveau Workplace : une seule identité traverse
  l'adaptateur, donc aucun « tenant A voit B ». Cohérent avec le **modèle mono-propriétaire**
  de Workplace (un Jarvis = une entreprise).
- ⚠️ **Pas de séparation par utilisateur Workplace** non plus : si Workplace devait un jour
  servir plusieurs utilisateurs *distincts* avec des facturations cloisonnées, il faudrait
  **propager l'identité de bout en bout** (token utilisateur, pas de service). C'est noté
  comme dette explicite, pas un bug — voir « Notes d'honnêteté ».

**Adaptateur (`briques/forge/main.py`).** Capacité `facturation` + 4 routes françaises,
erreurs claires, dégradation propre (réutilise `_appel_protege` / `_json_ou_erreur` de S17) :
- `GET  /facturation` — lister devis/factures + stats CA (encaissé / en attente), filtres `type`, `statut`.
- `POST /facturation` — créer un devis/une facture (entrée FR ; le core numérote et calcule HT/TVA/TTC).
- `POST /facturation/{id}/statut` — changer le statut (`payée` → encaissement).
- `POST /facturation/{id}/transformer` — devis → facture.

**Outils assistant (`core/outils.py`).** Convention Workplace respectée :
- **Lecture libre** : `forge_factures_lister`.
- **Action confirmée** (`confirme=true`) : `forge_facture_creer`, `forge_facture_statut`, `forge_facture_transformer`.

### Preuve E2E (stack live, 2026-06-07)

1. **Adaptateur direct** (port 5700) : créer une facture (2 950 € HT × 1,20 = **3 540 € TTC**,
   numérotée `FACT-2026-0001`) → marquer **payée** → **CA encaissé = 3 540 €**. Devis
   `DEVIS-2026-0001` → **transformé** en `FACT-2026-0002`. ✅
2. **Via l'assistant (LLM + Gateway)** :
   - Lecture : « liste mes factures + CA » → l'assistant appelle `forge_factures_lister`,
     rend un tableau juste (encaissé/en attente). ✅
   - Action : « crée une facture pour Garage Leroy, 1 200 € HT » → confirmation, puis
     `forge_facture_creer(confirme=true)` → facture réelle (1 440 € TTC). ✅
   - **Coût Gateway visible** sur `/assistant/usage` (appels routés comptés ; coût $0 car
     modèle local llama-cpp). ✅
3. **Dégradation** : routes mappent core/Keycloak absents en 502/503 clairs (motif S17, inchangé). ✅
4. **Nettoyage** : les données de test (clients fictifs) ont été supprimées — facturation
   re-vidée (CA = 0). ✅

### Chantier 2 — `crm` (motif S17 + résolution de pôle)

**Spécificité (vs `facturation`).** Le router `crm` scope les leads par **`pole_id` ET
`user_id`** — lister/créer exige un **pôle**, lui-même rattaché à une **venture**. Imposer ce
cérémonial venture→pôle à un Workplace **mono-entreprise** n'ajoute pas d'euro : l'adaptateur
le **masque** via `_resoudre_pole_crm()` qui **amorce paresseusement** (une fois) une venture
« Workplace » — le core crée alors 6 pôles par défaut, dont *Sales* — puis mémorise l'id du
pôle commercial. Contrat exposé : « prospects », pas « pôles ».

**Bug réel rencontré & corrigé (honnêteté).** Première version : résolution via
`GET /api/poles` → **liste vide en boucle** (3 ventures parasites créées). Cause : `list_poles`
filtre par `org_id` **quand l'utilisateur en a un**, or les pôles amorcés ont `org_id` **nul**
(l'adaptateur n'envoie pas de `X-Org-ID`) → aucun match. **Correctif** : passer par la
**venture** (`GET /api/ventures` scope par `owner_id`, fiable) puis `GET /api/ventures/{id}/poles`
(scope par `venture_id`, sans filtre org). Vérifié : **une seule** venture créée, réutilisée.

**Adaptateur (`briques/forge/main.py`).** Capacité `crm` + 3 routes FR :
- `GET  /crm` — lister les prospects + **pipeline** (valeur totale, ventilation par statut), filtre `statut`.
- `POST /crm` — ajouter un prospect (`{nom, entreprise?, email?, telephone?, statut?, valeur?, notes?}`).
- `POST /crm/{id}` — mettre à jour / **faire avancer** dans le pipeline (statut, valeur…).

**Outils assistant (`core/outils.py`).** **Lecture libre** : `forge_crm_lister`. **Actions
confirmées** : `forge_crm_creer`, `forge_crm_modifier`.

**Preuve E2E (stack live, 2026-06-07).**
1. Adaptateur (:5700) : lecture (bootstrap pôle *Sales*) → créer « Claire Fontaine » (8 000 €)
   → **avancer à `gagné`** → 2ᵉ prospect `qualifié` (3 500 €) → **pipeline = 11 500 €**
   (gagné 8 000 / qualifié 3 500). ✅ Une seule venture créée.
2. Via l'assistant (LLM + Gateway) : « montre mon CRM + pipeline » → `forge_crm_lister`,
   tableau + récap juste ; « ajoute Sophie Durand, 5 000 € » → confirmation puis
   `forge_crm_creer(confirme=true)` → prospect réel. **Coût Gateway visible** sur
   `/assistant/usage` (13 appels, **$0,0024** — repli payant déclenché). ✅
3. **Nettoyage** : prospects + venture/pôles d'amorçage supprimés, adaptateur redémarré
   (purge du cache pôle) → état re-vierge. Le bootstrap se recrée au 1er usage réel. ✅

### Chantier 3 — Bilan & ré-arbitrage

- **Coût d'intégration réel** : faible pour `facturation` (router déjà complet, ≈ 1 route +
  1 outil/fonction) ; **un cran au-dessus pour `crm`** à cause de la dépendance pôle/venture
  (résolution + 1 bug org_id corrigé) — mais toujours dans le motif adaptateur S17.
- **Usage** : les deux fonctions sont prouvées fonctionnelles, **pas encore d'usage métier
  réel** — à confirmer avant d'en brancher d'autres.
- **Chaîne commerciale bouclée** : `crm` (prospect gagné) → `facturation` (devis → facture →
  encaissement). C'est le cœur « rapproche d'un euro » du sprint.
- **Ré-arbitrage du backlog** : prochain candidat = **`stripe`** (encaissement en ligne réel,
  une fois les clés configurées) ; puis éventuellement `prospection` (LLM, alimente le CRM).
  Pilotage interne (`ventures`/`okr`/`forecast`) reste **gelé** tant que la valeur ne se confirme pas.

## Notes d'honnêteté technique

- **Le vrai risque, c'est la dispersion.** Forge a tant de routers que « tant qu'on y est » est
  irrésistible. Chaque router branché est une surface à maintenir, sécuriser, faire évoluer. Un
  router qui ne sert pas est une dette, pas un actif.
- **Critère unique de reprise** : *ça rapproche d'un euro ?* Si la réponse est « c'est cool » ou
  « ça pourrait servir », c'est **non** pour ce sprint.
- **Signal de gel** : si brancher le router n°1 coûte beaucoup plus que prévu, c'est l'info que la
  dette d'intégration de Forge dépasse sa valeur immédiate — décider **explicitement** de geler et
  réinvestir ailleurs (cf. note d'honnêteté de S17). Ne pas laisser l'inertie décider.
- **Dette d'identité (constatée en C1)** : les routers scopés par `user.sub` (comme `facturation`)
  vivent sous l'**identité de service unique** de l'adaptateur. C'est juste pour un Workplace
  **mono-propriétaire** (le cas actuel), mais **faux** dès qu'il faut cloisonner plusieurs
  utilisateurs Workplace distincts. Avant tout scénario multi-utilisateur réel : propager le
  **token de l'utilisateur** (et non le token de service) à travers l'adaptateur. Ne pas brancher
  d'autres routers `user_id`-scopés en croyant l'isolation acquise — elle ne l'est qu'au niveau org
  (S18), pas au niveau utilisateur via l'adaptateur.
