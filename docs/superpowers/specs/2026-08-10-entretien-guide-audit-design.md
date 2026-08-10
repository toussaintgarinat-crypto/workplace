# Design — Entretien guidé IA (sprint 2/4 de la capacité « Audit d'entreprise → conception de solutions »)

**Date** : 2026-08-10
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Deuxième des 4 sprints qui comblent les manques du pipeline « Audit d'entreprise →
conception de solutions » (ordre validé : entité → **entretien** → ROI/CDC → connecteurs).
Dépend du sprint 1 (voir `2026-08-10-entite-entreprise-unifiee-design.md`) : la Venture
(type=audit) de Forge porte désormais `geo_object_id`, `audit_id` et `profil_entreprise`
(JSON, 9 catégories qualitatives), et un endpoint `GET /ventures/{id}/dossier` les agrège.

Sans ce sprint, `profil_entreprise` reste vide et `briques/audit` ne reçoit que ce que
l'utilisateur pense à uploader manuellement — le système ne « creuse » jamais un processus
comme le décrit la vision (« comment arrive une demande client » → « qui répond » → « combien
de temps » → …).

Clarifications actées avec l'utilisateur pendant le brainstorming :
- **Greffé sur Forge**, à côté de `Ventures` — cohérent avec le sprint 1, pas de nouvelle
  brique ni de logique métier ajoutée au Cœur (qui reste un orchestrateur générique).
- `briques/audit` n'a **aucune API d'écriture incrémentale** (vérifié dans le code :
  `POST /auditer` = analyse LLM en un seul bloc à partir de `doc_ids`, `POST /audits/import` =
  réinsertion complète). Décision : ne pas y toucher. Le transcript de l'entretien est pousssé
  vers `ingestion` comme un document de plus, puis `POST /auditer` est rappelé avec tous les
  `doc_ids` de la venture (transcript + documents déjà uploadés) — réutilise l'analyse
  existante telle quelle.
- Deux types de sections dans le squelette d'entretien, traitées différemment : les 9
  catégories qualitatives du `profil_entreprise` (sprint 1) sont extraites et patchées
  directement après chaque réponse ; les 4 zones de processus de la vision (Commercial/
  Production/Administratif/Communication) sont accumulées en transcript brut, analysées plus
  tard par `briques/audit`.
- La logique de relance est **dynamique pilotée par LLM, à l'intérieur d'un squelette de
  sections fixe** — ni script rigide, ni LLM totalement libre (qui oublierait des sections).
- **Pause/reprise obligatoire** : l'état est persisté à chaque tour, un dirigeant peut
  reprendre des jours plus tard.

## État constaté du code (vérifié, pas supposé)

- `briques/audit/main.py:148-179` (`POST /auditer`, `POST /auditer/tout`) : prend une liste de
  `doc_ids`, lance `_lancer_audit` en tâche de fond, qui appelle une seule fois le LLM
  (`auditer(textes, nom_entreprise)`) et écrit `territoire/flux/problemes/priorites` en bloc
  (lignes 105-137). Aucun endpoint pour ajouter un fragment à un audit existant.
- `briques/audit/main.py:182-210` (`POST /audits/import`) : réinsère un audit complet,
  `id` préservé — prévu pour « reprise d'un dossier décroché », pas pour un ajout incrémental.
- `core/accord_action.py:73-82` (fonction `cle(fil, utilisateur)`) : précédent direct pour
  cloisonner un état de conversation par `(fil, personne)` plutôt que par fil seul — clé
  construite `f"{fil or 'sans-fil'}\x00{utilisateur or '-'}"` (leçon S222, deux personnes sur
  le même fil web ne doivent jamais partager un état). Motif à réutiliser pour savoir quel
  entretien est « actif » sur quel tour de conversation.
- Sprint 1 (ce même cadrage) : `GET /ventures/{id}/dossier`, `Ventures.profil_entreprise`
  (JSON, fusion attendue, jamais d'écrasement), pont déjà prouvé `venture → ingestion` (upload
  avec `venture_id`).

## Architecture

### 1. Nouveau module Forge : état d'entretien

Table `entretiens` (Forge) :
- `id`, `venture_id` (FK), `section_courante` (texte, ex. `"commercial"`,
  `"profil.personnel"`), `sections_couvertes` (JSON, liste des sections terminées),
  `transcript` (texte cumulatif, uniquement les sections de type « processus »), `statut`
  (`en_cours|termine`), `derniere_activite`, `created_at`.

### 2. Squelette de sections (fixe, sert de garde-fou)

Deux familles, jamais mélangées dans le traitement d'une réponse :

- **Processus** (accumulées en transcript brut, motif de l'exemple de la vision) :
  Commercial (prospection/demande entrante/qualification/devis/relance), Production
  (planning/intervention/compte rendu/suivi), Administratif (facturation/documents/
  comptabilité), Communication (email/téléphone/SMS/réseaux sociaux).
- **Qualitatif** (extraction structurée, patch direct de `profil_entreprise`) : les 9
  catégories du sprint 1 (organisation, activités, clients, fournisseurs, outils_utilises,
  personnel, contraintes, objectifs, problemes_connus).

Dans chaque section, le LLM décide de la relance (motif exact de la vision : une réponse
courte appelle une question de suivi ciblée) ; il ne quitte une section que lorsqu'elle est
jugée suffisamment couverte ou sur demande explicite de l'utilisateur (« passons à autre
chose »).

### 3. Endpoints Forge

- `POST /ventures/{id}/entretien/demarrer` — crée l'entretien s'il n'existe pas, ou reprend
  l'existant (`statut=en_cours`) en renvoyant la section courante + un rappel du dernier
  échange (« la dernière fois on parlait de… »).
- `POST /ventures/{id}/entretien/repondre {message}` — traite la réponse de l'utilisateur :
  si section « qualitatif », extraction LLM ciblée puis fusion dans
  `Ventures.profil_entreprise` ; si section « processus », ajout au `transcript`. Retourne la
  question suivante (LLM) ou le passage à la section suivante du squelette.
- `POST /ventures/{id}/entretien/terminer` — clôture (`statut=termine`), pousse `transcript`
  vers `ingestion` comme document lié (`venture_id`, voir sprint 1), puis rappelle
  `POST {AUDIT_URL}/auditer` avec tous les `doc_ids` de la venture.
- `GET /ventures/{id}/entretien/etat` — pour un affichage éventuel de progression (pas d'UI
  dans ce sprint, juste l'API).

Une ré-analyse (`/auditer`) peut aussi être déclenchée à la clôture d'une section « processus »
si l'utilisateur le demande explicitement (« lance l'analyse maintenant ») — jamais
automatiquement à chaque tour, pour ne pas multiplier les appels LLM coûteux.

### 4. Routage côté Cœur

Réutilise le motif `(fil, personne)` de `core/accord_action.py:73` plutôt que d'en inventer un
nouveau : tant qu'un entretien est `en_cours` pour la clé `(fil, personne)` associée à une
venture, les tours de conversation de ce fil sont routés vers `entretien/repondre` plutôt que
le chat libre habituel. Un mot-clé explicite (« pause », « on reprendra plus tard ») ou un
changement de sujet clair suspend le routage sans perdre l'état (rien n'est perdu, l'entretien
reste `en_cours`, juste plus « actif » sur ce tour).

Nouvelles capacités manifest (Forge) : `forge_entretien_demarrer`, `forge_entretien_repondre`
— niveau 1 (comme les autres capacités de pilotage), découvertes par le Cœur.

## Modèle de données

```sql
CREATE TABLE IF NOT EXISTS entretiens (
    id TEXT PRIMARY KEY,
    venture_id TEXT NOT NULL REFERENCES ventures(id),
    section_courante TEXT NOT NULL,
    sections_couvertes JSONB NOT NULL DEFAULT '[]',
    transcript TEXT NOT NULL DEFAULT '',
    statut TEXT NOT NULL DEFAULT 'en_cours',
    derniere_activite TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entretiens_venture ON entretiens(venture_id);
```

## Erreurs / dégradation

- Extraction LLM qui échoue ou renvoie un résultat incohérent sur une section qualitative :
  le tour n'est pas perdu — le message brut de l'utilisateur est de toute façon conservé dans
  un journal de conversation existant (Cœur) ; seule la fusion dans `profil_entreprise` est
  sautée pour ce tour, avec un statut `extraction_echouee` loggé (pas de blocage de
  l'entretien).
- `ingestion` injoignable à la clôture : `entretien.statut` reste `termine` mais un champ
  `sync_erreur` est renseigné ; retry manuel possible (rappel de `terminer`) sans reprendre tout
  l'entretien.
- `briques/audit` injoignable lors du rappel de `/auditer` après clôture : même traitement,
  best-effort, ne bloque jamais la clôture de l'entretien lui-même (le transcript reste dans
  `ingestion`, rejouable).
- Reprise après plusieurs semaines : le rappel de contexte (« la dernière fois… ») utilise les
  50 derniers caractères pertinents du transcript ou de la dernière extraction qualitative,
  jamais une donnée inventée si rien n'est disponible.

## Tests

- Forge : cycle complet démarrer → répondre (section qualitative, vérifie la fusion non
  destructive dans `profil_entreprise`) → répondre (section processus, vérifie l'ajout au
  transcript) → terminer (vérifie l'appel `ingestion` puis `/auditer`, mocké).
- Reprise : entretien `en_cours` interrompu, nouvel appel `demarrer` renvoie la bonne section
  et le bon rappel de contexte, sans perte de `sections_couvertes`.
- Routage Cœur : deux personnes sur le même fil web (`web:dashboard`) avec un entretien actif
  chacune — vérifie l'isolation par `(fil, personne)` (non-régression directe de la leçon
  S222), un tour de l'une ne doit jamais avancer l'entretien de l'autre.
- Panne : `ingestion` et `briques/audit` injoignables séparément à la clôture — l'entretien
  reste `termine`, `sync_erreur` renseigné, pas d'exception non gérée.

## Hors périmètre (explicitement)

- **UI dédiée** (barre de progression, affichage des sections) — capacités API/manifest
  seulement, l'entretien se vit entièrement dans le chat existant.
- **Correction manuelle** d'une extraction qualitative erronée par l'utilisateur — pas
  d'écran d'édition dans ce sprint (le dirigeant peut reformuler dans la conversation, l'IA
  refait l'extraction).
- **Entretien vocal** (téléphone/visio) — le pont `standard-telephonique`/`voix` n'est pas
  câblé ici ; l'entretien reste un flux de chat texte (Cœur) dans ce sprint.
- **Écriture incrémentale dans `briques/audit`** — écartée explicitement (voir Contexte),
  `briques/audit` continue de fonctionner en mode « analyse en un bloc », inchangé.
- **Relance proactive** (l'IA qui recontacte le dirigeant si l'entretien traîne) — hors
  périmètre, initiative laissée à l'utilisateur pour reprendre.
