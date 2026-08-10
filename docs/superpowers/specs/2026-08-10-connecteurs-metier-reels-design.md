# Design — Connecteurs métier réels (sprint 4/4 de la capacité « Audit d'entreprise → conception de solutions »)

**Date** : 2026-08-10
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Dernier des 4 sprints (ordre validé : entité → entretien → ROI/CDC → **connecteurs**).
Dépend du sprint 1 (`Ventures`/dossier) et se branche directement sur le sprint 3 (ROI) : un
connecteur compta réel peut faire basculer une estimation ROI de « hypothèse LLM » à
« fourni client ».

Une revue de code a établi que `briques/connecteurs` (PyAirbyte en librairie, cache DuckDB
isolé par tenant, explicitement **pas** un entrepôt analytique) est une infrastructure réelle
mais quasi vide de contenu métier : un seul connecteur exercé en test (`source-faker`), aucun
pont vers `geo`/`forge`/l'entité entreprise. Contrairement aux idées reçues, une partie du
périmètre « Connexions » de la vision (CRM/messagerie/agenda) est déjà couverte nativement par
d'autres briques (`mail`, `agenda`, `telephonie` — provider-agnostiques, pas du batch ETL) : le
vrai gain de `connecteurs` porte sur les systèmes tiers **sans** brique Workplace dédiée — un
CRM externe déjà en place chez le client, ou un outil de comptabilité/ERP.

Clarifications actées avec l'utilisateur pendant le brainstorming :
- Le sprint couvre **à la fois** l'infrastructure générique du pont (source ↔ venture) **et**
  la preuve concrète avec deux connecteurs : un **CRM tiers** (contacts/deals déjà en place
  chez le client) et un **compta/ERP** (alimente le ROI du sprint 3 avec de vrais chiffres).
- Le principe de sécurité déjà en place est **conservé sans modification** : créer/configurer
  une source n'est pas une capacité de l'assistant (`briques/connecteurs/main.py:137-140` —
  les identifiants tiers ne doivent jamais transiter par une conversation LLM, donc par le
  journal, le cache sémantique, ou le fournisseur de modèle). Seul le déclenchement d'un sync
  déjà configuré reste une action assistant, comme aujourd'hui.
- Seuls les connecteurs à **authentification par clé API simple** sont dans le périmètre — les
  connecteurs nécessitant un flux OAuth avec redirection restent hors périmètre (trop de
  travail d'UI pour un sprint).
- Le nom exact des connecteurs PyAirbyte (CRM/compta) sera confirmé en plan d'implémentation
  selon leur disponibilité réelle sur PyPI — non bloquant pour ce cadrage.

## État constaté du code (vérifié, pas supposé)

- `briques/connecteurs/stockage.py:52-61` (table `sources`) : `tenant`, `nom`, `connecteur`,
  `config_chiffree` (chiffrée via `coffre.chiffrer`, ligne 106), `flux`, `cree_le`. Isolation
  par `tenant` uniquement — aucune notion de venture/client.
- `briques/connecteurs/main.py:135-148` (`POST /sources`) : docstring explicite — « Créer une
  source n'est PAS une capacité de l'assistant, à dessein… On les saisit par l'API ou par
  l'atelier ; l'assistant, lui, déclenche et consulte. » Principe à préserver intégralement.
- `briques/connecteurs/main.py:262` (`POST /sources/{id}/sync`) : déclenchement de sync,
  action assistant existante (niveau capacité à vérifier en plan, mais le principe « déclencher
  = OK » est déjà acté par le code actuel).
- `briques/connecteurs/pont/executer.py:70-75` (`_cache`) : `DuckDBCache` par source
  (`schema_name=job["schema"]`), isolé — confirmé « pas un entrepôt » par le manifest
  (`main.py:9-12`), les données synchronisées restent dans ce cache local.
- Un seul connecteur exercé (`source-faker`, `test_integration_pyairbyte.py:38`), tests réseau
  sautés par défaut (`CONNECTEURS_TEST_RESEAU=1`) — aucun connecteur métier réel n'est
  aujourd'hui configuré ni testé.
- Pont déjà prouvé du même type de motif à réutiliser : `veille-prospection/orchestration.py:
  44-49` → `POST {FORGE_URL}/crm/import-lot` (`briques/forge/main.py:712`), dé-doublonné,
  testé des deux côtés.
- Sprint 1 (ce même cadrage) : `Ventures.profil_entreprise` (JSON, fusion non destructive),
  `GET /ventures/{id}/dossier`. Sprint 3 : `POST {AUDIT_URL}/audits/{id}/chiffrer
  {cout_horaire}` — bascule le ROI de `hypothese_llm` à `fourni_client` si un coût horaire
  réel est fourni.

## Architecture

### 1. Lien source ↔ venture

`sources` gagne une colonne `venture_id TEXT NULL` (référence souple, motif des sprints
précédents — pas de FK physique inter-service). Une source de connecteur est désormais
rattachée à un dossier client précis, pas seulement au tenant Workplace. Toujours créée/
configurée uniquement par API (jamais par l'assistant, principe préservé).

### 2. Mappeur CRM → Forge + profil_entreprise

Après un sync réussi d'une source dont le `connecteur` est de type CRM (liste blanche
restreinte, pas de détection automatique) :
- lecture des tables `contacts`/`deals` (noms exacts à confirmer en plan selon le connecteur
  choisi) dans le cache DuckDB de la source,
- transformation en liste de prospects (même forme que `veille-prospection`),
- `POST {FORGE_URL}/crm/import-lot` — **réutilisation stricte** du pont déjà prouvé, aucun
  changement côté Forge,
- mise à jour de `Ventures.profil_entreprise.clients` (comptage, quelques exemples) sur la
  venture liée à la source.

### 3. Mappeur Compta/ERP → ROI

Après un sync réussi d'une source de type compta/ERP :
- lecture des tables de temps passé / masse salariale (à confirmer en plan selon le
  connecteur),
- agrégation d'un coût horaire réel par pôle (commercial/production/administratif, même
  découpage que le sprint 3),
- `POST {AUDIT_URL}/audits/{audit_id}/chiffrer {cout_horaire: {...}}` où `audit_id` est celui
  référencé par la venture liée à la source (`Ventures.audit_id`, sprint 1) — fait basculer les
  entrées ROI concernées de `hypothese_llm` à `fourni_client`.

### 4. Déclenchement

Le mappeur correspondant tourne en tâche de fond juste après un sync réussi
(`_syncer`/`_lancer_sync`, `main.py:210-262`), best-effort — un échec du mappeur n'invalide
jamais le sync lui-même (les données restent dans le cache DuckDB, consultables/rejouables).

## Modèle de données

```sql
ALTER TABLE sources ADD COLUMN venture_id TEXT;
```

Aucune nouvelle table : les mappeurs lisent le cache DuckDB existant et écrivent via les API
déjà en place (`forge`, `audit`) — pas de persistance supplémentaire côté `connecteurs`.

## Erreurs / dégradation

- Mappeur CRM/compta échoue (schéma inattendu, table absente) : le sync reste marqué réussi
  (les données brutes ont bien atterri dans le cache), un statut `mapping_echoue` est journalisé
  sur la ligne `syncs` correspondante — jamais bloquant, rejouable manuellement.
- `forge` ou `audit` injoignable au moment du mappage : même traitement, best-effort, retry
  possible sans relancer tout le sync PyAirbyte (coût réseau/temps évité).
- Connecteur configuré avec un `venture_id` inexistant ou supprimée : le mappeur logue une
  erreur explicite plutôt que de créer des données orphelines côté Forge/audit.

## Tests

- `connecteurs` : `venture_id` sur création/lecture de source (non-régression : source sans
  `venture_id` reste valide, motif « ancien format » des sprints précédents).
- Mappeur CRM : sync mocké avec un cache DuckDB de test (contacts/deals factices) → vérifie
  l'appel `POST /crm/import-lot` avec la forme attendue, et la mise à jour de
  `profil_entreprise.clients`.
- Mappeur compta : sync mocké → vérifie l'appel `POST /audits/{id}/chiffrer` avec un
  `cout_horaire` cohérent avec les données de test, et le changement de statut `fourni_client`
  côté audit (test d'intégration avec le sprint 3, mocké).
- Pannes : mappeur CRM/compta en échec chacun séparément → sync reste `reussi`,
  `mapping_echoue` journalisé, aucune exception non gérée.
- Non-régression : le principe « création de source jamais via l'assistant » reste vérifié
  (aucune capacité manifest n'expose `POST /sources` ou `PUT /sources/{id}` à l'assistant).

## Hors périmètre (explicitement)

- **Connecteurs OAuth** (flux de redirection/consentement) — API-key uniquement dans ce
  sprint.
- **Détection automatique du type de connecteur** (CRM vs compta vs autre) — liste blanche
  explicite maintenue à la main, pas d'inférence.
- **UI de configuration de source** — reste l'API existante ou l'atelier, pas de nouvel écran
  dans ce sprint.
- **Extension à d'autres types de connecteurs** (Google Workspace, Microsoft 365 — déjà
  partiellement couverts par `mail`/`agenda`/`telephonie` natifs) — hors périmètre, décision
  explicite de ne pas dupliquer les briques natives déjà provider-agnostiques.
- **Entrepôt analytique** sur les données synchronisées — décision déjà actée (ADR) et non
  remise en cause : le cache DuckDB reste local à la source, les mappeurs ne font que des
  extractions ciblées vers des consommateurs précis (Forge, audit).
