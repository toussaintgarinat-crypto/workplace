# Design — Entité Entreprise unifiée (sprint 1/4 de la capacité « Audit d'entreprise → conception de solutions »)

**Date** : 2026-08-10
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Vision globale : transformer Workplace en « AI Business Solution Architect » — collecte
d'informations sur une entreprise cliente → cartographie → détection de problèmes →
proposition de solutions → cahier des charges → génération d'une app → déploiement → mesure
des résultats. Une revue de code complète (pas seulement des manifests) a établi qu'un
squelette fonctionnel et testé existe déjà pour la moitié la plus dure du parcours
(`briques/audit` 5300 → `briques/generateur` 5400 : cartographie processus/problèmes/
priorités, génération d'app + bundle Docker, boucle de mesure d'usage `revue.py`). Quatre
manques ont été identifiés et priorisés avec l'utilisateur, dans cet ordre : **1. Entité
Entreprise unifiée (ce spec) → 2. Entretien guidé IA → 3. ROI chiffré + cahier des charges
exportable → 4. Connecteurs métier réels (CRM/ERP/Google Workspace/365)**.

Ce premier sprint pose le socle de données : aujourd'hui, l'identité d'une entreprise
(`briques/geo`), ses processus/problèmes (`briques/audit`) et ses documents
(`briques/ingestion`) ne sont reliés par aucun identifiant commun fiable. Sans ce socle, un
entretien guidé (sprint 2) n'aurait nulle part où écrire ses réponses.

Clarifications actées avec l'utilisateur pendant le brainstorming :
- La nouvelle entité est **greffée sur Forge**, en donnant enfin une vraie substance au champ
  `Ventures.type = 'audit'` (aujourd'hui un simple libellé d'affichage frontend, sans logique
  métier — voir État constaté). Pas de nouvelle brique dédiée : on réutilise l'auth
  multi-tenant (JWT Keycloak, `X-Org-ID`, `OrganizationMembers`) déjà en place dans Forge.
- Le sprint **relie** les données existantes (pas de duplication) ET **ajoute** les champs
  qualitatifs qui n'existent nulle part aujourd'hui : Organisation, Activités, Clients,
  Fournisseurs, Outils utilisés, Personnel, Contraintes, Objectifs, Problèmes connus (déclarés
  par le dirigeant — distincts des problèmes *détectés* par les couches Ishikawa/Pareto de
  `briques/audit`). Le sprint 2 (entretien guidé) remplira ces champs progressivement ; rien
  n'oblige à les remplir dès ce sprint.
- **Deux systèmes d'audit coexistent** et sont référencés séparément, avec leurs rôles
  clarifiés plutôt qu'unifiés de force : les `AuditMissions` internes de Forge (rapport LLM
  léger par pôle, `forge/core/app/routers/audit.py`) restent un audit interne côté agence ;
  `briques/audit` (5300, couches Territoire/Flux/Problèmes/Priorités) reste le seul moteur qui
  alimente réellement `briques/generateur` — c'est lui qui doit être référencé pour la suite du
  pipeline.
- Le client audité doit pouvoir se connecter en lecture seule sur son propre dossier (pas
  seulement un usage interne consultant).

## État constaté du code (vérifié, pas supposé)

- `briques/forge/forge/core/app/models/generated.py:729` (`Ventures`) : `owner_id`, `org_id`
  (FK), `nom`, `type` (défaut `'own'`), `statut`. `ventures.py:96` : le champ `type` est un
  simple texte, **aucune logique métier différenciée** entre `'own'` et `'audit'` côté backend
  — seulement un libellé côté frontend (`VentureDetail.jsx:428-429` : « 🏠 Own Venture » vs
  « 🔍 Mission Audit »).
- `generated.py:805` (`AuditMissions`) : rattachée à `pole_id` (pas directement à la venture),
  liée à `AuditDocuments`/`AuditFindings`/`AuditRecommendations`/`Rapports` — génère un rapport
  LLM markdown. Système interne à Forge, découplé de `briques/audit`.
- `briques/geo/stockage.py:59-67` (`geo_objects`) : socle générique (`id`, `tenant`, `type`,
  `lat/lon`, `metadata` JSON). `briques/geo/domaine.py:199-248`
  (`normaliser_entreprise`) : remplit `metadata` avec `nom`, `naf`, `adresse`, `commune`,
  `siren`, `dirigeants`, `effectifs`. Enrichissement web (`main.py:184-206`) ajoute `site`,
  `email`, `telephone`, `reseaux_sociaux`. Vue dédiée `_prospect_crm` (`main.py:208-219`).
  C'est un profil entreprise réel mais souple (JSON libre, pas de colonnes typées).
- `briques/ingestion/stockage.py:49` (table `documents`) : **aucune colonne**
  entreprise/organisation. `entreprise_id` (lignes 121, 145) n'est qu'une clé libre dans
  `metadonnees.classement`, posée a posteriori par le Cœur, sans contrainte d'intégrité ni
  index.
- `briques/audit/main.py:16-22` (`INGESTION_URL`, `INGESTION_KEY`) : pont HTTP réel et testé
  vers `ingestion` (`_recuperer_textes` lignes 75-93, `_recuperer_tous_ids` lignes 96-99,
  `manifest.json` déclare `depends_on: ["ingestion", "gateway"]`, testé dans
  `audit/test_audit.py:79-99` y compris le cas 502 si `ingestion` est injoignable). En
  revanche, `briques/audit` n'a aujourd'hui aucune notion de « quelle entreprise » — un audit
  est un objet flottant, sans lien vers `geo` ni vers Forge.
- `briques/forge/forge/core/app/auth.py:1-50` : middleware JWT Keycloak, auto-provisioning,
  résolution d'org via header `X-Org-ID` validé contre `OrganizationMembers`. C'est le socle
  d'auth multi-tenant sur lequel greffer un rôle client scopé.
- Pont déjà prouvé du même type (référence HTTP inter-brique, pas de FK physique — briques =
  services/bases séparées) : `veille-prospection/orchestration.py:44-49` → `POST
  {FORGE_URL}/crm/import-lot` (`briques/forge/main.py:712`), testé des deux côtés. C'est le
  motif à reproduire ici plutôt qu'inventer un nouveau pattern.

## Architecture

### 1. Extension `Ventures` (Forge)

Nouvelles colonnes, directement sur la table existante (pas de table séparée — la venture
reste l'unité naturelle d'un dossier client) :

- `geo_object_id TEXT NULL` — référence souple (pas de FK physique inter-service) vers un
  `geo_objects.id` de type entreprise.
- `audit_id TEXT NULL` — référence souple vers un audit de `briques/audit` (5300).
- `profil_entreprise JSONB NULL` — les 9 catégories qualitatives (`organisation`, `activites`,
  `clients`, `fournisseurs`, `outils_utilises`, `personnel`, `contraintes`, `objectifs`,
  `problemes_connus`), chacune une liste de chaînes ou un texte libre selon le champ — même
  souplesse que `geo.metadata`, pas de sous-tables relationnelles.

Le lien vers les `AuditMissions` internes existantes n'est pas modifié structurellement (il
continue de passer par `pole_id`) ; il est simplement exposé dans le dossier agrégé (point 2)
et documenté comme « audit interne léger », distinct de `audit_id` (« audit business complet »).

### 2. Nouvel endpoint agrégateur `GET /ventures/{id}/dossier`

Un seul appel qui rassemble :
- identité (`GET {GEO_URL}/objets/{geo_object_id}` si renseigné),
- résumé de l'audit business (`GET {AUDIT_URL}/audits/{audit_id}` si renseigné),
- liste des `AuditMissions` internes existantes de la venture (via ses pôles, code déjà
  existant),
- liste des documents liés (`GET {INGESTION_URL}/documents?venture_id=...`, voir point 3),
- `profil_entreprise` tel quel.

C'est ce endpoint que consommeront le sprint 2 (entretien guidé, pour savoir ce qui manque
encore) et `briques/generateur` à terme (au lieu d'appeler `audit` seul).

### 3. Fix `briques/ingestion` — `venture_id` indexé

Nouvelle colonne `venture_id TEXT NULL` sur `documents`, avec index, remplissable à
l'upload. La clé JSON existante `metadonnees.classement.entreprise_id` n'est **pas retirée**
dans ce sprint (rétrocompatibilité, zéro migration destructive) — les deux coexistent, la
colonne indexée devient la source de vérité pour les nouveaux documents.

### 4. Rôle `client_lecture` scopé (Forge)

Nouvelle valeur de rôle sur `OrganizationMembers`, portant en plus un `venture_id` (pas
seulement un `org_id`). Un membre avec ce rôle :
- a accès en lecture seule à `GET /ventures/{id}/dossier` **pour cette venture précisément**,
- n'a accès à aucune autre venture de l'organisation, ni à aucune route d'écriture.

`auth.py` : `UserContext` gagne un `venture_scope: str | None`, vérifié par un dépendant FastAPI
dédié sur les routes concernées (motif proche de la résolution `org_id` existante).

## Modèle de données

Migration Forge (Alembic ou équivalent déjà en place) :

```sql
ALTER TABLE ventures ADD COLUMN geo_object_id TEXT;
ALTER TABLE ventures ADD COLUMN audit_id TEXT;
ALTER TABLE ventures ADD COLUMN profil_entreprise JSONB;

ALTER TABLE organization_members ADD COLUMN venture_scope TEXT;
-- role existant élargi pour accepter 'client_lecture' en plus des rôles actuels
```

Migration `ingestion` :

```sql
ALTER TABLE documents ADD COLUMN venture_id TEXT;
CREATE INDEX IF NOT EXISTS idx_documents_venture ON documents(venture_id);
```

Aucune nouvelle table côté `geo` ni `briques/audit` — `metadata`/structure existante suffit,
seule la référence entrante (`Ventures.geo_object_id`/`audit_id`) est nouvelle.

## Flux

**Onboarding** : création d'une `Venture(type='audit')` → liaison optionnelle à un
`geo_object_id` existant (ou création à la volée via l'API `geo`) → `profil_entreprise` vide au
départ. **Documents** : upload via `ingestion` avec `venture_id` renseigné. **Lecture** :
`GET /ventures/{id}/dossier` agrège tout en un appel, y compris pour l'assistant du Cœur.

## Erreurs / dégradation

Cohérent avec le principe « repli honnête » déjà appliqué dans tout le repo (jamais de donnée
inventée) : si `geo` ou `briques/audit` est injoignable au moment d'agréger le dossier, la
section correspondante du JSON de réponse porte un statut explicite `"indisponible"` (avec le
dernier `geo_object_id`/`audit_id` connu) plutôt que d'être omise silencieusement ou simulée.
Un document `ingestion` orphelin (venture supprimée) n'est jamais supprimé automatiquement —
purge hors périmètre de ce sprint.

## Tests

Motif exact déjà en place (`audit/test_audit.py`, `forge/test_crm_import_lot.py`) : appel réel
testé, mock des dépendances réseau, jamais simulé silencieusement.

- Forge : création Venture + liaison `geo_object_id`/`audit_id`, lecture du dossier agrégé (cas
  nominal, cas panne `geo` seul, cas panne `audit` seul, cas panne des deux), contrôle d'accès
  `client_lecture` (positif sur sa venture, 403 sur une autre venture de la même org).
- `ingestion` : upload avec `venture_id`, requête `GET /documents?venture_id=...` retourne
  uniquement les documents de cette venture ; document sans `venture_id` (ancien format) reste
  lisible normalement (non-régression).
- Test d'intégration bout-en-bout (mock réseau) : Venture créée → geo_object lié → document
  ingéré avec `venture_id` → dossier agrégé contient bien les trois.

## Hors périmètre (explicitement)

- **Entretien guidé** pour remplir `profil_entreprise` — sprint 2, séparé.
- **Calcul de ROI** et **cahier des charges exportable** — sprint 3, séparé.
- **Vrais connecteurs CRM/ERP/Google Workspace/365** — sprint 4, séparé ; `briques/connecteurs`
  reste hors périmètre (aujourd'hui : un seul connecteur testé, `source-faker`, aucun pont vers
  `geo`/Forge).
- **Retrait ou fusion des `AuditMissions` internes de Forge** — laissées telles quelles,
  seulement référencées/documentées comme système distinct.
- **Migration destructive** de `ingestion.metadonnees.classement.entreprise_id` vers la
  nouvelle colonne — les deux coexistent, pas de script de bascule des documents existants.
- **UI dédiée** (écran de dossier client dans le frontend Forge) — capacités API/manifest
  seulement dans ce sprint ; l'intégration visuelle est un sujet séparé si besoin.
- **Propagation `venture_id` dans `briques/audit`** au-delà de la référence entrante
  (`Ventures.audit_id`) — `briques/audit` n'a pas besoin de connaître Forge pour fonctionner,
  seul Forge connaît l'audit qu'il référence (cohérent avec le sens du pont
  `audit → ingestion` déjà existant : celui qui a besoin de la donnée va la chercher).
