# WORKPLACE — Document de référence

> **Projet** : Workplace — assistant IA modulaire + usine à applications sur-mesure
> **Auteur** : Toussaint Garinat
> **Créé le** : 2026-06-02
> **Statut** : 🟢 Usine pilotée par le Cœur — une entreprise livrée en **une commande** (docs → audit → app → bundle, S5), **décrochable / reprenable** sans perte (cycle de vie, S6), pilotable **en langage naturel** par l'**assistant du Cœur** — qui sert toute la solution et a une **mémoire persistante** (S7–S8) — voir Sprints S5–S8
> **Langue du projet** : français (code, commentaires, messages)

Ce fichier est la **source de vérité** du projet. Toute décision importante s'écrit ici
avant d'être codée. Si une info contredit le code, c'est le code qu'on corrige OU ce
document qu'on met à jour — jamais les deux qui divergent en silence.

---

## 1. Vision — les deux objectifs

### 🎯 Objectif 1 — L'usine à applications sur-mesure
Une chaîne en 3 temps qui transforme une entreprise en application :

1. **Audit / ETL** — un mode *Extract-Transform-Load* qui aspire **toutes** les
   informations d'une entreprise (documents, PDF, fichiers, données…).
2. **Ingestion par l'IA** — l'IA lit et **comprend** l'entreprise.
3. **Génération** — création automatique d'une **application sur-mesure** pour cette
   entreprise : **tableau de bord** + **messagerie interne** + **autres outils**.

### 🎯 Objectif 2 — Le « Jarvis » personnel
Un **assistant central (Workplace)** qui peut **tout gérer** : piloter les modules,
la mémoire, les projets, la collaboration. C'est le cœur qui orchestre tout le reste.

> **Catégorie** : ce qu'on construit s'appelle, en 2026, un « Jarvis réel » — un
> assistant IA auto-hébergé qui n'agit pas que par le chat mais **agit vraiment**
> (mémoire persistante, outils, voix, automatisation). L'objectif 1 va **plus loin**
> que les Jarvis grand public : il ne nous assiste pas seulement, il **fabrique des
> outils pour d'autres entreprises**. C'est la valeur unique du projet.

---

## 2. Principes fondateurs (NON négociables)

1. **Architecture « noyau + briques » (modèle Neovim).**
   Un **cœur stable** qui change rarement + des **briques** (modules/plugins) branchées
   autour. Les briques communiquent **uniquement par des contrats clairs** (API),
   jamais en s'imbriquant. On peut réécrire l'intérieur d'une brique sans rien casser
   tant que son contrat ne change pas.

2. **On peut ajouter une nouvelle brique à tout moment.** ⭐
   Le cœur possède un **registre de briques**. Ajouter une brique = **déposer un
   dossier** avec un petit fichier `manifest`, pas réécrire Workplace. Briques futures
   possibles : Comptabilité, CRM, Signature électronique, etc. Le système est conçu
   **ouvert** dès le départ.

3. **Versioning sémantique (SemVer) + CHANGELOG.**
   Chaque brique a son numéro de version (`vMAJEUR.MINEUR.CORRECTIF`). Images Docker
   taguées par version → **retour arrière en 1 commande** si une mise à jour casse.
   Git : une branche par fonctionnalité.

4. **Réutiliser l'open-source, réécrire le reste.**
   - On **réutilise tel quel** les vrais outils open-source faits pour ça (ex. MemPalace).
   - On **s'inspire des principes** d'autres projets sans copier leur code ni leur identité.

5. **Identité 100 % à nous.**
   - Nom du projet : **Workplace**.
   - ❌ On **n'utilise pas** le nom « Gungnir » ni le concept/marque « Conscience »
     (Conscience v4, Volition Pyramid, etc.) — c'est l'univers d'une autre personne.
     Gungnir nous sert uniquement de **source d'inspiration sur les patterns** (système
     de plugins, marketplace, versioning) ; son code (licence BSL) **n'est pas copié**.
   - Le module mémoire s'appelle **« Mémoire »** (vocabulaire neutre), pas « Conscience ».

6. **Honnêteté technique.**
   « Le code existe » ≠ « ça tourne ». On distingue toujours *prêt à tester* de
   *prouvé en marche de bout en bout*. On avance **brique par brique**, jamais tout d'un coup.

---

## 3. Architecture cible

```
                        ┌─────────────────────────────────┐
                        │           WORKPLACE              │
                        │   Cœur stable + REGISTRE DE       │
                        │   BRIQUES (ajout à chaud)         │ ◄── permet d'ajouter
                        └───────────────┬─────────────────┘     une brique quand on veut
                                        │  (contrats API / MCP)
        ┌───────────────┬───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼               ▼
   ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
   │ MÉMOIRE │    │   LLM    │    │  COLLAB  │    │  AGENTS  │    │  (futur) │
   │MemPalace│    │ Gateway  │    │   Oria   │    │  Forge   │    │   ...    │
   └─────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘

   ────────────── BRIQUES MÉTIER (Objectif 1 — à construire) ──────────────
   ┌────────────┐      ┌────────────┐      ┌─────────────────────────────┐
   │ 1. ETL /   │  →   │ 2. AUDIT   │  →   │ 3. GÉNÉRATEUR D'APP          │
   │  INGESTION │      │  (l'IA     │      │   • Tableau de bord          │
   │ docs/PDF/  │      │  comprend  │      │   • Messagerie interne (Oria)│
   │ OCR/web    │      │ l'entreprise)│    │   • Autres outils            │
   └────────────┘      └────────────┘      └─────────────────────────────┘
```

**Anatomie d'une brique** (contrat commun à toutes) :
```
ma-brique/
├── manifest.json     # nom, version, couche (frontend/backend), ce qu'elle offre, ce dont elle a besoin
├── routes/           # ses points d'entrée (API)
├── frontend/         # son interface (optionnel)
└── README.md         # à quoi elle sert
```
Le cœur lit les `manifest.json`, découvre les briques et les branche automatiquement.

---

## 4. Inventaire vérifié des briques existantes

> Cartographie réalisée le 2026-06-02. « Vérifié » = config Docker validée et/ou code
> exécuté, pas seulement « le fichier existe ». Environnement : Docker 29.2 actif,
> Node 25, Python 3.14. Un `Makefile` orchestre déjà tout dans `~/Desktop/workspace`.

| Brique | Rôle Workplace | Source | Code réel | Vérifié | Statut |
|---|---|---|---|---|---|
| ~~MemPalace~~ → **Memory** | Mémoire | `briques/memoire/memory` (projet déplacé dans la brique, port 5600) | FastAPI + Postgres/pgvector | conteneur ✅ + retenir/rappeler + sémantique ✅ | 🟢 **Remplace MemPalace** (S8, 2026-06-05) |
| **Gateway** | Cerveau LLM | `workspace/gateway` | 91 lignes (config LiteLLM) | config ✅ | 🟢 Prêt (clé OpenRouter requise) |
| **Oria** | Collaboration / messagerie | `workspace/oria` | ~18 600 lignes (84 py + 50 ts) | config ✅ | 🟡 Setup Matrix avant 1er démarrage |
| **Forge** | Agents IA + RAG | `briques/forge` (core vendorisé) | ~28 400 lignes (la plus grosse) | brique ✅ branchée (Gateway+Mémoire+Keycloak+Qdrant) | 🟢 **Fonctionnel prouvé** (S17) — agent + RAG tournent depuis l'assistant (auth de service, schéma migré, Qdrant) ; **S19** UI intégrée au dashboard (iframe, SSO realm `oria`) ; **S20** 1ers routers métier rebranchés : **`facturation`** (devis/factures/encaissement) + **`crm`** (prospects/pipeline), prouvés E2E ; **S21** Stripe **réel** (SDK + clé au coffre chiffré + **webhook signé**) — code livré, prouvé **offline** (signature/chiffrement), live à rejouer avec clé `sk_test_` ; **S22** emails **réels** + **relances d'impayés** J+7/15/30 (anti-doublon) — prouvé offline (envoi SMTP local réel), live à rejouer avec SMTP |
| ~~Assistant (stub ETL/OCR)~~ | retiré | `workspace/assistant` | — | — | ⚪ Stub jamais activé, **retiré du registre** (S8) — l'ETL réel est `briques/etl` ; le projet `workspace/assistant` reste le modèle de l'assistant du Cœur (S7) |
| **Strategic App Builder** | Générateur d'app | `Desktop/application de création d'application/strategic-app-builder-studio-v2.html` | 694 Ko (1 fichier HTML) | marche déjà | 🟢 Autonome |
| **Donnees** | Persistance serveur des apps | `briques/donnees` | FastAPI + SQLite (port 5500) | conteneur ✅ + CRUD bout-en-bout ✅ | 🟢 Livré (S2, 2026-06-04) |

**Total : ~93 000 lignes de code réel. Les 5 configs Docker sont valides.**

### Où chaque brique se branche
- **MemPalace** → la **Mémoire** de Workplace (remplace l'idée de « Conscience »).
- **Gateway (LiteLLM)** → le **routeur LLM** unique (OpenRouter, Ollama, Groq, etc.).
- **Oria** → la **messagerie interne** livrée aux entreprises (objectif 1) **ET** la
  couche collaboration de Workplace (objectif 2). Bonus : visio (LiveKit) + agents
  IA résidents dans les canaux.
- **Forge** → moteur d'**agents + RAG**, base de l'audit/ingestion.
- **Assistant** → contient déjà l'**ETL** (markitdown, Tesseract OCR, pdf2image).
- **Strategic App Builder** → base du **générateur d'app**.

---

## 5. Ce qui reste à construire (la vraie valeur)

Sur les 5 grandes briques du Jarvis (Cœur, Mémoire, LLM, Collaboration, Agents),
**4 existent déjà**. Le travail neuf se concentre sur :

1. **Le Cœur Workplace + le registre de briques** — l'orchestrateur qui découvre et
   branche les briques (le « Neovim » du projet).
2. **Les 3 briques métier de l'objectif 1** :
   - **ETL / Ingestion** — aspirer + lire les infos de l'entreprise (s'appuie sur Assistant + Forge/RAG).
   - **Audit** — l'IA analyse et produit une fiche de compréhension de l'entreprise.
   - **Générateur d'app** — assemble dashboard + messagerie (Oria) + outils (s'appuie sur App Builder).

---

## 6. Feuille de route (par étapes, brique par brique)

- [x] **0. Cartographie** — inventaire vérifié des briques existantes ✅ (2026-06-02)
- [x] **1. Document de référence** — ce fichier ✅ (2026-06-02)
- [x] **2. Première brique vivante** — **MemPalace tourne pour de vrai** ✅ (2026-06-02).
      19 tiroirs mémorisés depuis WORKPLACE.md, recherche sémantique FR validée (score 0.72).
      Outils hors du contenu : venv + palace dans `~/Desktop/.workplace-mem/`.
      Lancement : `~/Desktop/.workplace-mem/venv/bin/python -m mempalace --palace ~/Desktop/.workplace-mem/palace <cmd>`
- [x] **3. Deuxième brique** — **Gateway (LiteLLM) vivant** ✅ (2026-06-02).
      Chat de bout en bout en **100 % local via Ollama** (modèle `ollama/llama3`), zéro clé API.
      Port **4001** (le 4000 est pris par `fleuriste-litellm-1`). `OLLAMA_URL=http://host.docker.internal:11434`.
      Test : `curl http://localhost:4001/v1/chat/completions -H "Authorization: Bearer sk-master-change-this" ...`
      Reste à relier Gateway ↔ Mémoire (au moment du Cœur).
- [x] **4. Cœur Workplace** — squelette du cœur + registre de briques (manifest loader) ✅ (2026-06-02).
      FastAPI sur port **5100**. 6 briques enregistrées via `briques/*/manifest.json`.
      Endpoints : `GET /briques`, `GET /briques/{nom}`, `POST /briques/reload`, `GET /sante-globale`.
      Gateway pingée et confirmée ok depuis le cœur (`host.docker.internal:4001`).
      Lancement : `cd ~/Desktop/Workplace/core && make up`
- [x] **5. Brancher Oria** — messagerie + collaboration ✅ (2026-06-02).
      10 services healthy : backend (8000), frontend (3003), keycloak (8081), dendrite/Matrix (8010),
      livekit (7880), minio (9106), pgbouncer, redis, etcd, db.
      Cœur confirme Oria ok via `/sante-globale`. Lancement : `cd ~/Desktop/workspace/oria && docker compose up -d`
- [x] **6. Brique ETL / Ingestion** — premier vrai morceau de l'objectif 1. ✅ (2026-06-02).
      FastAPI sur port **5200**. Endpoints : `POST /ingerer`, `POST /ingerer/url`, `GET /documents`, `GET /documents/{id}`.
      Extraction : MarkItDown (PDF/Word/Excel/PowerPoint/HTML/CSV) + PyMuPDF fallback + OCR Tesseract (fra+eng).
      Stockage SQLite dans volume Docker `/data/etl.db`. Cœur confirme ETL ok via `/sante-globale`.
      Lancement : `cd ~/Desktop/Workplace/briques/etl && make up`
- [x] **7. Brique Audit** — l'IA comprend une entreprise test. ✅ (2026-06-02).
      FastAPI sur port **5300**. 4 couches LLM séquentielles : Territoire, Flux, Problèmes, Priorités.
      Audit asynchrone + stockage SQLite. Endpoint : `POST /auditer/tout`, `GET /audits/{id}`.
      Correctifs : `texte_extrait` (ETL) et liste paginée `documents.documents[]` gérés.
      Lancement : `cd ~/Desktop/Workplace/briques/audit && make up`
- [x] **8. Brique Générateur** — premier tableau de bord généré bout-en-bout. ✅ (2026-06-02).
      FastAPI sur port **5400**. Lit `GET /audits/{id}`, appelle LLM pour un plan (couleurs, KPIs, actions),
      génère un tableau de bord HTML Bootstrap 5 complet (sidebar + 5 sections : Résumé, Territoire, Flux, Problèmes, Priorités).
      Stockage SQLite. Endpoint : `POST /generer`, `GET /apps/{id}/html` (téléchargement HTML).
      Pipeline prouvé de bout en bout : ETL → Audit → Générateur → HTML téléchargeable.
      Lancement : `cd ~/Desktop/Workplace/briques/generateur && make up`
- [x] **9. Vertical slice complet** — 1 entreprise test : docs → audit → mini app livrée. ✅ (2026-06-03).
      Entreprise test fictive **« Menuiserie Lefèvre & Fils »** (4 docs : présentation, finances, processus/problèmes, objectifs).
      Chaîne prouvée bout-en-bout : ETL (ingestion 4 docs) → Audit (4 couches : DDD/VSM/Ishikawa+Pareto/Chemin critique+PERT, ~54s) →
      Générateur → **tableau de bord HTML sur-mesure** (« MenuiseriePilot », thème bois, nav = vrais domaines Devis/Production/Achats/
      Relation Client/Qualité, KPIs tirés des docs : délai devis 10j, reprise 2%). Rendu validé visuellement (capture).
      **LLM** : Ollama local **inutilisable** sur ce Mac Intel sans GPU (3min20/appel → timeouts). Bascule sur **OpenRouter via le Gateway**.
      Modèles **gratuits** instables (503/429 selon le moment : gemma-31b/qwen down, kimi trop lent, nemotron-120b OK mais ~lent).
      Slice finalisé sur **`openai/gpt-4o-mini`** (cheap, 2s/appel, fiable) à la demande pour avancer.

- [ ] **10. App opérationnelle (objectif 1 complet)** — en cours (2026-06-03).
      Le Générateur ne produit plus un simple dashboard d'audit mais une **app opérationnelle** :
      • **Modules CRUD interactifs** par entité métier (Devis, Commande de bois, Planning, Dossier client) :
        tableau + formulaire d'ajout typé + suppression, **persistance navigateur (localStorage)**, données d'exemple. Ajout prouvé en live.
      • **Pareto CA × Temps × Pénibilité** : croise la part de CA et la part de temps/occupation par activité
        (révèle les activités « chronophages » = beaucoup de temps pour peu de CA), + pénibilité + badge rentabilité + graphe Chart.js.
      • Vue **« Application proposée »** : modules livrés ✓ vs proposés + priorisation des fonctionnalités (MoSCoW).
      • Robustesse : `gabarit.py` tolère les variations de schéma LLM (helpers `_d`/`_l`/`_first`, casse des clés MoSCoW, chemin_critique liste/dict).
      Audit enrichi : `repartition_ca` (montant/%, temps_pct, pénibilité par activité).
      Persistance serveur (au-delà du localStorage) et édition des enregistrements : **faits en S2 (2026-06-04)**.
      Messagerie interne (Oria) intégrée à l'app livrée : **faite en S3 (2026-06-04)**.

### 🗺️ Backlog de sprints organisés (objectif 1 — usine à apps qui scale)

> Leçon du **Strategic App Builder** (`~/Desktop/application de création d'application/`) : il sait déjà
> *décomposer un projet en briques à brancher* (`analyze decompose`, `export appforge-blueprint`), mais
> c'est un **mono-fichier React/Babel in-browser + localStorage**, mono-utilisateur, sans back ni déploiement
> → **bonne idée (briques branchables), implémentation qui ne scale pas**. On garde l'idée, on la porte sur
> l'architecture **noyau + briques** de Workplace (briques réelles, multi-entreprise, déployables).

**État actuel (Sprint 0 — FAIT)** : ETL → Audit → Générateur → app opérationnelle v1 (modules CRUD localStorage,
Pareto CA×Temps×Pénibilité, analyses, vue « Application proposée », export dossier par entreprise).

| Sprint | Objectif | Pourquoi | Statut |
|---|---|---|---|
| **S0** | Vertical slice + app opérationnelle v1 | preuve bout-en-bout | ✅ fait |
| **S1 — Briques scalables** | Le générateur **assemble l'app à partir d'un registre de briques** au lieu d'un gabarit monolithique. Ajouter une capacité = ajouter une brique. | **Répond directement au « ça ne scale pas »** | ✅ fait (2026-06-03) |
| **S2 — Persistance & multi-utilisateur** | Remplacer le localStorage par une **vraie persistance serveur** (API CRUD + DB par app) → condition pour livrer en entreprise (plusieurs utilisateurs). | sans ça, l'app reste un gadget mono-poste | ✅ fait (2026-06-04) |
| **S3 — Messagerie interne (Oria)** | L'app livrée embarque une messagerie (espace + salons par entreprise, SSO). | objectif 1 explicite | ✅ fait (2026-06-04) |
| **S4 — Déploiement & livraison** | Déployer l'app d'une entreprise de façon reproductible (packaging docker / multi-tenant) + auth Keycloak. Au-delà de l'export d'un fichier. | mise en place réelle chez le client | ✅ v1 fait (2026-06-04) — auth Keycloak de l'app = évolution |
| **S5 — Cœur / Jarvis** | Piloter l'usine depuis le Cœur : audit→génération→déploiement d'une entreprise en une commande + tableau des entreprises livrées. | l'orchestrateur (objectif 2) | ✅ v1 fait (2026-06-04) |
| **S6 — Cycle de vie des entreprises** | **Décrocher** une entreprise livrée (état rassemblé dans un dossier portable + retirée des bases centrales) puis la **reprendre** pour la modifier, et la re-décrocher. Aller-retour sans perte. | garder la solution principale propre ; sortir/rentrer une entreprise à la demande | ✅ v1 fait (2026-06-05) |
| **S7 — Assistant du Cœur (« Jarvis »)** | Un **agent conversationnel** qui pilote l'usine : on lui parle en langage naturel, il consulte l'état et **agit** (livrer / décrocher / reprendre) via des outils, avec **confirmation** avant toute action. | Objectif 2 « Jarvis réel » : il n'assiste pas seulement, il **agit** | ✅ v1 fait (2026-06-05) |
| **S8 — Assistant de toute la solution + Mémoire** | Élargir l'assistant à **toutes les briques** (ETL, Générateur, Données, Mémoire…), lecture **et** actions (avec confirmation). Intégrer le projet **Memory** comme brique (`memoire`) → l'assistant a une **mémoire persistante** (retenir / rappeler). | l'assistant sert la solution entière, pas que l'usine ; il se souvient | ✅ v1 fait (2026-06-05) |

### 🗺️ Backlog S28+ (décidé le 2026-06-10)

> Construit à partir des **dettes ouvertes** des sprints S19–S27 + S138 et de **deux features
> nouvelles** retenues : le **briefing quotidien** (le Jarvis parle le premier) et
> **« l'app vivante »** (re-audit post-livraison → revenu récurrent). Ordre choisi pour que
> chaque sprint débloque le suivant.

| Sprint | Objectif | Pourquoi / ce qu'il solde | Statut |
|---|---|---|---|
| **S28 — Clôture LIVE groupée (Stripe + emails + comptes)** | Configurer une fois les prérequis communs (vrai SMTP, clé Stripe `sk_test_`, rôle Keycloak `manage-users` + SMTP realm `oria`) puis **rejouer les 3 flux en LIVE** : paiement Stripe (S21), envoi email + relance d'impayé déclenchée à la main (S22), compte client auto + lien « définis ton mdp » (S23). | **Solde 3 dettes d'un coup** (S21/S22/S23, tous « code livré + prouvé offline, reste LIVE ») ; c'est la chaîne qui rapproche de l'euro : devis → facture → paiement → relance → compte client. | ✅ PROUVÉ LIVE (dev) 2026-06-10 — `docs/sprints/S28-cloture-live-groupee.md` |
| **S29 — Brique `horloge` (planificateur)** | Une petite brique (ou un module du Cœur étendant `proactif.py`) qui exécute des **tâches périodiques déclarées par les autres briques** (contrat manifest : quoi, quand, idempotence). Premiers branchements : **relances J+7/15/30** (S22) et **sync Google Agenda** (S27, pull périodique). | Trois sprints butaient sur le même mur (cron des relances, déclencheur de sync, proactif) ; une seule brique fidèle au modèle noyau+briques débloque tout. **Prérequis de S30.** | ✅ LIVRÉ + PROUVÉ LIVE (dev) 2026-06-10 — module `core/horloge.py` (contrat `taches` dans les manifests), 7 tests verts, relances déclenchées HTTP 200 + sync agenda 400 toléré + cadence respectée. `docs/sprints/S29-horloge-planificateur.md` |
| **S30 — Briefing quotidien (Jarvis proactif)** | Chaque matin, l'assistant **vient vers l'utilisateur** : RDV du jour (agenda + pont Google), factures approchant J+7/15/30, pipeline CRM, coût LLM de la veille — synthèse rédigée par l'**économe local** (routage S138, coût ~0), livrée dans le chat (pastille 🔔 existante) et/ou en message Oria. Techniquement : nouvelles coroutines dans `CHECKS` de `proactif.py` + 1 synthèse LLM, déclenchée par `horloge`. | Le comportement qui définit un Jarvis : **parler le premier**. Petit, visible tous les matins, capitalise S10/S20/S22/S27/S138. | ✅ LIVRÉ + PROUVÉ LIVE (dev) 2026-06-10 — `core/briefing.py` (4 sources tolérantes → synthèse par l'économe **gratuit** coût 0 $ → rappel 🔔), tâche `briefing-quotidien` déclarée dans `briques/noyau/manifest.json` et **déclenchée par l'horloge S29 en self-call HTTP** (S29→S30 prouvé bout en bout), 7 tests verts. `docs/sprints/S30-briefing-quotidien.md` |
| **S31 — « L'app vivante » (re-audit post-livraison)** | Boucler la chaîne de l'usine : les données d'usage **consenties** remontées par le pont S24 (+ nouveaux documents) alimentent un **re-audit** de l'entreprise livrée → le générateur **propose un incrément** (« module Planning utilisé 40×/jour, Devis jamais ; le Pareto a changé ; je propose X »), à valider avant toute génération. S'appuie sur : pont consenti (S24), cycle de vie décrocher/reprendre (S6), audit (S7). | L'app livrée cesse d'être one-shot : **revenu récurrent** (contrat d'évolution) — le critère « ça rapproche d'un euro ? » mieux que tout le reste du backlog. | ✅ LIVRÉ CODE + 5 tests offline verts 2026-06-11 — `briques/generateur/revue.py` (mesure d'usage **consentie** S24 → Pareto + modules dormants → proposition d'incrément par le LLM, repli heuristique honnête), endpoints `/apps/{id}/revue` + `/revue/valider` (**proposer ≠ générer**, garde-fou humain). **PROUVÉ LIVE (dev) 2026-06-11** — vraie stack `donnees` 5500 + Gateway 4001 + `generateur` 5400 : app réelle (cabinet kiné) consentement `{planning, devis}`, usage semé planning=5/devis=0/factures=3 → revue mesure planning=5 (100 %) + `devis` dormant + **`factures` invisible** (3 enr. réels dans `donnees` mais 0 compté → souveraineté tenue), proposition `source=llm`, `valider` → `validee`. **Backlog S28–S31 entièrement soldé (code + LIVE).** `docs/sprints/S31-app-vivante.md` |
| **S32 — « Appliquer l'incrément » (régénération enrichie)** | Dernier pas de « l'app vivante » : une proposition de revue **validée** (S31) est **appliquée** — les modules proposés sont réinjectés dans le plan livré et l'app est **régénérée** (même gabarit). Suite directe de la dette S31 « appliquer l'incrément ». | Rend le **revenu récurrent** réel : l'app livrée évolue pour de vrai au lieu de rester one-shot. Chaîne complète **proposer ≠ valider ≠ appliquer**. | ✅ LIVRÉ CODE + **5 tests offline verts** + **PROUVÉ LIVE (dev) 2026-06-11** — `briques/generateur/appliquer.py` (fonction pure `construire_plan_enrichi`, idempotente + non destructive) + endpoint `POST /apps/{id}/revue/appliquer` (régénère via `generer_html`, **refuse si non `validee`** → 409, anti double-application). LIVE vraie stack : LLM propose 2 modules → injectés comme entités CRUD, plan 3→5 entités, HTML régénéré les embarque, 2 garde-fous 409 tenus. `docs/sprints/S32-appliquer-increment.md` |
| **S33 — Horloge sur la revue (« app vivante » périodique)** | Déclarer la revue S31 comme **tâche périodique** du manifest générateur : l'horloge S29 balaie les apps **consentantes** et propose un incrément, l'application S32 restant manuelle. | Rend la boucle « app vivante » **autonome** (le Jarvis travaille sans qu'on le pousse), fidèle au modèle noyau+briques. | ✅ LIVRÉ CODE + **4 tests offline** + **PROUVÉ LIVE (dev) 2026-06-11** — tâche `revue-app-vivante` (manifest) + `POST /revues/balayage` (best-effort) + `revue.doit_reviser` (souveraineté + ne pas écraser une `validee`). LIVE bout-en-bout : l'horloge du Cœur **découvre** (cadence 168 h) et **déclenche** la tâche (HTTP 200) ; 14 apps balayées → 1 proposée, 13 ignorées (12 sans consentement + 1 `validee`), 0 erreur. `docs/sprints/S33-horloge-revue.md` |
| **S34 — Schéma fin des modules ajoutés** | À l'application d'un incrément (S32), demander au **LLM** le schéma de champs du module (vocabulaire de l'entreprise) au lieu d'un CRUD générique ; repli générique si Gateway KO. | L'incrément n'est plus passe-partout : module **taillé pour l'entreprise**. | ✅ LIVRÉ CODE + **7 tests offline** + **PROUVÉ LIVE (dev) 2026-06-11** — `prompt_schema_module` + `construire_plan_enrichi_llm` (async, repli générique, `schema: llm\|generique`). LIVE : modules « Rapports d'activité » (séances planifiées/réalisées, taux de réussite) + « Gestion des ressources » (disponibilité Disponible/Occupé/En maintenance) générés avec champs typés métier. `docs/sprints/S34-schema-fin-modules.md` |
| **S35 — Durcissement pont Google (state OAuth anti-CSRF)** | Solder la dette sécurité S27 : remplacer `state = user_id` brut (prévisible, falsifiable) par un jeton **signé HMAC-SHA256** opaque, vérifié au callback. | Sécurité **avant ouverture publique** du pont Google : anti-CSRF, on ne fait plus confiance à une identité en clair. | ✅ LIVRÉ CODE + **31 tests verts dans l'image Docker réelle** (dont 7 nouveaux) 2026-06-11 — `services/oauth_state.py` (`emettre`/`verifier`, TTL 10 min, stateless, secret dérivé de `VAULT_SECRET`), `/connect` signe, `/callback` vérifie (400 si falsifié/expiré). Reste LIVE = consentement Google réel (prérequis S27). `docs/sprints/S35-durcissement-pont-google.md` |
| **S36 — Forge : course de provisioning (S19) + propagation d'identité (S20)** | Deux dettes du core Forge : (1) double provisioning au 1er login concurrent → 500 ; (2) l'adaptateur n'envoie qu'un token de service, l'identité utilisateur ne traverse pas. | Robustesse (plus de 500 au login) + préparer le **2ᵉ utilisateur réel** (identité propageable). | ✅ LIVRÉ CODE + **tests verts** 2026-06-11 — `_provision_user`/`_ensure_personal_org` idempotents sous course (savepoint + re-select), **prouvé dans l'image réelle du core** (174 passés, 0 régression) ; adaptateur propage `X-Forge-User-Token` si présent (repli service, **flux S17/S24 inchangés**), prouvé offline 3/3. Reste LIVE (S20) = 2ᵉ utilisateur réel + émission du token côté Cœur. `docs/sprints/S36-forge-identite-concurrence.md` |

**En parallèle (pas des sprints, mais à ne pas perdre)** :
- ~~**Durcissement S27** : `state` OAuth opaque (anti-CSRF) + redirect prod~~ → ✅ **traité en S35**
  (state signé HMAC) ; reste la preuve LIVE du consentement Google réel.
- ~~**Dette identité Forge (S20)**~~ → ✅ **capacité livrée en S36** (l'adaptateur propage
  `X-Forge-User-Token` si présent) ; reste LIVE = 2ᵉ utilisateur réel + émission du token côté Cœur.
  Ne pas brancher de router en croyant l'isolation acquise tant que ce LIVE n'est pas fait.
- ~~**Bug de concurrence S19** (course au 1er login → double provisioning, 500 auto-réparé)~~ →
  ✅ **corrigé en S36** (savepoint + re-select, prouvé dans l'image réelle du core).
- **Mesure réelle S138** : activer le journal sur le trafic normal de l'assistant, prouver le
  **shadow routing LIVE** et vérifier les cibles (−40 % coût, ≥25 % hit) — sinon recalibrer.
- **Long-tail Oria UX** (palettes intentionnelles) : opportuniste, au fil de l'eau.

#### ✅ S1 livré — architecture briques du générateur (2026-06-03)
- `gabarit.py` ne contient plus un `generer_html` monolithique : un **registre de briques** (`_REGISTRE`)
  où chaque brique est un constructeur `ctx -> list[vue]`. L'app s'assemble en parcourant le registre.
  Briques internes : tableau de bord, application proposée, **outils CRUD** (1 par entité), territoire, flux, problèmes, priorités.
- **Auto-découverte** : tout fichier déposé dans `briques/generateur/briques_app/*.py` exposant
  `construire(ctx) -> list[vue]` est branché automatiquement (modèle « noyau + briques » appliqué aux apps générées).
  Prouvé avec `briques_app/notes.py` (module « Notes internes » ajouté sans toucher au cœur).
- Contrat d'une vue : `{"id","label","icone","categorie"("pilotage"|"outils"|"analyse"|…),"html"}` ;
  une brique défaillante est ignorée sans casser l'app. `ctx` = audit + plan + données dérivées (entités, pareto…).
- Reste (scalabilité « profonde ») : extraire chaque brique interne dans son propre fichier de `briques_app/` ;
  versionner les briques ; catalogue/marketplace de briques.

#### ✅ S2 livré — persistance serveur & multi-utilisateur (2026-06-04)
- **Nouvelle brique `donnees` (Persistance)** sur port **5500** — magasin **CRUD générique
  multi-tenant** (SQLite, volume Docker `donnees_data`). Tout est rangé par `(app_id, entite_id)` ;
  chaque enregistrement reçoit un **identifiant serveur stable (uuid)** → édition/suppression fiables
  (l'ancien localStorage supprimait par position dans le tableau). **CORS ouvert** (les apps tournent
  depuis n'importe quelle origine). Endpoints : `GET/POST …/enregistrements`, `PUT/DELETE …/{id}`,
  `POST …/seed` (idempotent : ne réécrase pas une entité déjà peuplée), `GET /apps/{app}/resume`,
  `DELETE /apps/{app}` (purge), `GET /sante`. 10 briques dans le registre du Cœur.
- **Générateur — deux modes de livraison** (la bascule annoncée ci-dessous est faite) :
  • **autonome** (défaut) : 1 fichier HTML + localStorage, mono-poste (rétrocompatible) ;
  • **hébergé** (`{"persistance":"hebergee"}` sur `POST /generer`) : l'app parle à la brique `donnees`
    → **données partagées entre utilisateurs**. À la génération, le serveur **sème** les exemples du plan
    dans `donnees`. URLs configurables : `DONNEES_URL_INTERNE` (serveur→données) et `DONNEES_URL_PUBLIQUE`
    (navigateur→données, injectée dans l'app).
- **Moteur JS de l'app refondu** : une couche d'accès unique `Store` (list/create/update/remove) qui
  cible l'API en mode hébergé ou le localStorage en mode autonome. **Édition des enregistrements ajoutée**
  (modal pré-rempli), suppression par `_id`, message clair si le serveur de données est injoignable.
- **Migration douce** : colonne `mode` ajoutée à `apps.db` via `ALTER TABLE` (anciennes apps → `autonome`,
  zéro perte). Le LISEZMOI d'export décrit désormais le mode (autonome vs hébergé).
- **Prouvé bout-en-bout** (sans LLM, via fixture) : app générée en mode hébergé servie dans un navigateur
  (Playwright) → la ligne semée se charge **depuis le serveur** ; ajout « Bernard » → présent côté serveur ;
  **rechargement complet de la page** (état navigateur vidé) → Bernard **revient du serveur** ; édition
  (montant 4 800 → 5 500, `_maj` > `_cree`) et suppression confirmées côté serveur. Mode autonome
  re-testé OK (localStorage). Brique `donnees` aussi validée **conteneurisée** (`make up` + CRUD + volume).

#### ✅ S3 livré — messagerie interne Oria embarquée dans l'app (2026-06-04)
Pipeline prouvé bout-en-bout au navigateur (Playwright) : **docs → audit → app hébergée →
SSO Keycloak → espace + salons Oria → message envoyé et persisté dans Matrix** (vérifié côté
serveur). Les 6 sous-tâches :

| # | Tâche | Statut |
|---|---|---|
| S3.1 | Cartographie API Oria (auth, espaces, salons, Matrix) | ✅ |
| S3.2 | Décision archi : messagerie = mode **hébergé** uniquement | ✅ |
| S3.3 | Provisionner un espace Oria + 1 salon / bounded_context à la génération | ✅ |
| S3.4 | Module « Messagerie » dans le gabarit (widget Matrix natif) | ✅ |
| S3.5 | SSO Keycloak entre l'app et Oria (OIDC Authorization Code + PKCE) | ✅ |
| S3.6 | Test bout-en-bout : messagerie de Menuiserie Lefèvre | ✅ |

**Comment ça marche**
- **Provisioning serveur** (`generateur/oria_provisioning.py`) : à la génération d'une app
  *hébergée + messagerie*, le générateur obtient un **token de compte de service Keycloak**
  (client confidentiel `workplace-provisioner`, *service account* + mapper d'audience →
  `oria-app` ; secret dans l'env `ORIA_PROVISIONER_SECRET`). Il crée via l'API Oria un **world**
  (= espace entreprise) + un **building** + **1 salon par bounded_context** de l'audit (+ un salon
  « Général »). `world_id` + salons (avec `matrix_room_id`) sont stockés dans `apps.db`
  (colonnes `oria_world_id`, `oria_salons`) et exposés par `GET /apps/{id}`.
- **Widget dans l'app** (`generateur/briques_app/messagerie.py`, auto-découvert) : onglet
  « Messagerie ». **SSO** = OIDC **Authorization Code + PKCE** à la main (zéro dépendance JS)
  contre Keycloak avec le **même client `oria-app`** que le frontend Oria → session partagée
  (vrai single sign-on). Après login : `GET /api/auth/me` (identifiants Matrix), `POST
  /api/worlds/{id}/rejoindre` (adhésion + invitation aux salons), `POST …/join/{room}` (Matrix),
  puis lecture/écriture **directe via l'API Matrix** (dendrite, port 8010) avec le
  `matrix_access_token` de l'utilisateur. Polling 4 s.
- **Config injectée** : les URLs publiques (`ORIA_URL_PUBLIQUE`, `MATRIX_URL_PUBLIQUE`,
  `KEYCLOAK_URL_PUBLIQUE`) + `world_id` + salons sont injectés dans l'app à la génération.

**Pré-requis opérationnels mis en place (Keycloak realm `oria`)**
- Client confidentiel **`workplace-provisioner`** (service account + mapper audience `oria-app`).
- Origine **`http://localhost:5400`** ajoutée aux *redirect URIs* + *web origins* de `oria-app`
  (pour le SSO depuis l'app servie par le générateur).
- **CORS** Oria : `ALLOWED_ORIGINS` du backend inclut désormais `http://localhost:5400`
  (ajouté à `~/Desktop/workspace/oria/.env`).
- Utilisateur de démo **`menuiserie-demo` / `Demo1234!`** (pour le test E2E).

**Limite assumée (dette → évolution)** : les salons sont créés **NON chiffrés** (type Oria hors
« texte/mixte ») pour permettre ce widget léger en lecture/écriture directe Matrix. L'**E2EE
complet** passera par l'**embed du frontend Oria** (iframe) — non retenu en v1 car la SPA Oria ne
deep-linke pas vers un world par URL et Keycloak bloque le login en iframe. À traiter si le chiffrement
de bout en bout devient requis pour la livraison.

✅ **Point d'architecture transverse (S2 fait, prépare S3.2)** : la bascule **deux modes de livraison** est
en place. **« autonome léger »** (1 fichier HTML, localStorage, mono-poste) reste le défaut ; **« hébergé
complet »** (persistance serveur via la brique `donnees`, multi-utilisateur) est livré par S2. La même bascule
débloque S3 : la messagerie Matrix exigera elle aussi le mode hébergé. Reste pour S3 à brancher Oria dessus.

#### ✅ S4 v1 livré — déploiement reproductible (bundle Docker par entreprise) (2026-06-04)
Au-delà de l'export d'un seul fichier HTML, le Générateur **empaquette l'app en bundle Docker
autonome et reproductible**, livrable tel quel et lancé d'**une seule commande**
(`docker compose up -d --build`). Prouvé bout-en-bout au navigateur (Playwright).

- **Nouvel endpoint `POST /apps/{id}/packager`** (générateur v0.2.0) → écrit dans
  `~/Desktop/Workplace/apps_exportees/<entreprise>-deploiement/` :
  ```
  <slug>-deploiement/
  ├── docker-compose.yml   # 2 services : web (nginx) + donnees (persistance DÉDIÉE)
  ├── .env                 # PORT_APP / PORT_DONNEES (modifiables)
  ├── web/index.html       # l'app (config réseau externalisée)
  ├── web/config.js        # window.WP_CONFIG = { apiBase, appId } — éditable sans régénérer
  ├── donnees/             # la brique persistance BÂTIE SUR PLACE (build reproductible)
  │   └── seed.json        # données d'exemple de l'entreprise
  └── LISEZMOI.txt         # guide de déploiement
  ```
- **Multi-tenant par déploiement** : chaque bundle embarque **sa propre** instance de la brique
  `donnees` (volume Docker dédié) → runtime **totalement indépendant** du stack de dev. Prouvé :
  un enregistrement saisi dans le bundle (port 5510) **n'apparaît pas** dans le `donnees` central
  (port 5500) — isolation réelle.
- **Config runtime** (`gabarit.py`) : l'app lit `window.WP_CONFIG` (fichier `config.js` du bundle)
  qui **surcharge** la config « cuite » à la génération → le **même HTML se déploie n'importe où**
  sans régénération. Mode autonome (fichier unique, sans `config.js`) inchangé : repli sur la config cuite.
- **Auto-seed reproductible** (`donnees`) : au démarrage, si `SEED_FILE` pointe sur un JSON monté
  (`{app_id:{entite_id:[…]}}`), la brique sème les exemples **idempotemment** (entités vides seulement)
  → `docker compose up` suffit pour une app pré-remplie. Vérifié : « seed initial : 10 enregistrement(s) ».
- **Build reproductible** : la source de la brique `donnees` est montée en lecture seule dans le
  conteneur générateur (`/briques_src/donnees`) et **copiée** dans chaque bundle → l'image se rebâtit
  sur n'importe quelle machine, sans dépendre des images/chemins de la machine de dev.
- **Preuve E2E (Playwright)** : audit → génération hébergée → `packager` → `docker compose up` du bundle
  Menuiserie → app servie sur **:8090**, parlant à sa **propre** persistance sur **:5510**
  (`CONFIG.apiBase = http://localhost:5510`, `HEBERGE=true`) → seed visible → création « PREUVE S4 » →
  **rechargement complet de la page** → l'enregistrement **revient du serveur** du bundle.

**Limite assumée (dette → évolution)** : l'**auth Keycloak de toute l'app** (gating du tableau de bord
derrière un login, pas seulement l'onglet Messagerie de S3) n'est pas dans cette v1 : elle exige
d'enregistrer l'URL de **chaque** déploiement dans le realm Keycloak (config par client) et un
reverse-proxy/OIDC devant nginx. La brique S3 fournit déjà l'OIDC PKCE (client `oria-app`) réutilisable.
Le cœur de l'app (tableau de bord + saisies + persistance) tourne sans cette brique.

#### ✅ S5 v1 livré — le Cœur pilote l'usine en une commande (2026-06-04)
Le **Cœur (v0.2.0, port 5100)** n'est plus seulement un registre passif : il **orchestre toute
la chaîne de l'objectif 1** — ETL → Audit → Génération (→ Packaging) — **en une seule commande**,
et tient le **tableau des entreprises livrées**. Prouvé bout-en-bout (Playwright + API).

- **Orchestrateur** (`core/orchestrateur.py`) : enchaîne les briques **uniquement par leurs
  contrats HTTP** (aucune logique métier réécrite). Résolution des URLs depuis le **registre**
  (port du manifest + `BRIQUE_HOST`, override possible par env `ETL_URL`/`AUDIT_URL`/`GENERATEUR_URL`).
  Polling des étapes async (audit, génération) jusqu'à `termine`/`erreur` (timeout configurable).
  Toute erreur est **attribuée à son étape** (`EchecEtape`) → diagnostic clair.
- **Une commande** : `POST /usine/livrer` (multipart) — `fichiers` (uploads, optionnels),
  `nom_entreprise`, `persistance` (`hebergee`/`autonome`), `messagerie` (Oria), `packager` (bundle
  Docker S4). Sans fichiers, l'audit porte sur les documents déjà présents dans l'ETL. Le **nom
  saisi par l'utilisateur prime** ; le nom dérivé par l'audit ne sert que si l'utilisateur a laissé
  le défaut. Lance un pipeline asynchrone et rend un `id` de livraison à suivre.
- **Tableau des entreprises livrées** : `GET /usine/livraisons`, `GET /usine/livraisons/{id}`
  (suivi temps réel), `DELETE`. Persistance **SQLite dans un volume Docker dédié** (`core_data`,
  `/data/livraisons.db`) : statut global, **journal par étape** (ingestion/audit/génération/
  packaging), `doc_ids`/`audit_id`/`app_id`, récap du bundle, horodatages, erreurs.
- **Dashboard du Cœur enrichi** (`/dashboard`) : deux onglets — *Registre de briques* (existant) et
  **Usine à apps** (nouveau) : formulaire « Nouvelle livraison » (upload + options) + cartes de
  livraison avec **progression visuelle par étape** (pastilles animées) et liens **Aperçu / HTML**
  de l'app dès qu'elle est livrée. Rafraîchissement auto 4 s.
- **Preuve E2E** : livraison de **Menuiserie Lefèvre & Fils** en une commande depuis le Cœur
  (4 docs uploadés → `ingestion:termine` → `audit f3a9a9e1:termine` → `app 6d8e0a9b:termine` →
  `packaging:termine`, statut **`livree`**). App **MenuiserieOps** servie (HTTP 200, 56 Ko) ;
  bundle Docker écrit dans `apps_exportees/menuiserie-lef-vre-et-fils-deploiement/` (9 fichiers).
  Livraison **persistée au redémarrage** du conteneur (volume vérifié). Capture : `docs/captures/s5-usine-tableau-livraisons.png`.

**Limite assumée (dette → évolution)** : la livraison est lancée mais **non annulable/relançable**
depuis le tableau (pas de retry par étape) ; pas d'authentification sur `/usine/*` (réservé au
réseau local de dev). Le déploiement reste local (`docker compose` sur la machine) — le cloud
multi-tenant viendra plus tard.

#### ✅ S6 v1 livré — cycle de vie : décrocher / reprendre une entreprise (2026-06-05)
Une entreprise livrée a son état **éparpillé dans plusieurs briques** : documents (ETL), audit
(Audit), app générée + HTML + refs Oria (Générateur), enregistrements saisis (Données). S6 permet
de la **sortir entièrement** de la solution principale (sans la perdre) puis de la **réinjecter** à
l'identique pour la modifier — aller-retour **sans perte**, autant de fois qu'on veut.

- **Dossier portable** (`apps_exportees/<slug>-dossier/`) : `dossier.json` rassemble **tout** l'état
  (format `workplace-dossier-v1` : documents avec texte extrait, audit, app + plan, enregistrements
  groupés par entité **avec leurs `_id`/horodatages**), + `app.html` (consultable hors-ligne) +
  `LISEZMOI.txt`. Écrit **avant** toute suppression (le dossier est la source de vérité une fois décroché).
- **Décrocher** (`POST /usine/livraisons/{id}/decrocher`) : collecte (lecture seule) l'état des briques,
  écrit le dossier, **puis retire vraiment** l'entreprise des bases centrales (DELETE docs ETL, audit,
  app Générateur, données Données). La livraison passe `livree → decrochee` et pointe vers le dossier.
  **La solution principale redevient propre.**
- **Reprendre** (`POST /usine/livraisons/{id}/reprendre`) : relit le dossier sur disque et **réinjecte**
  via les contrats import de chaque brique — **tous les identifiants préservés** (`INSERT OR REPLACE`,
  mêmes `doc_ids`/`audit_id`/`app_id`/`_id` d'enregistrements). Statut `decrochee → livree`. L'entreprise
  est de nouveau modifiable, puis re-décrochable.
- **Pattern « noyau + briques » respecté** : le Cœur (`core/cycle_de_vie.py`) ne réécrit aucune logique
  métier — il n'orchestre que des **contrats HTTP export/import** ajoutés à chaque brique (ETL
  `POST /documents/import` ; Audit `POST /audits/import` ; Générateur `GET /apps/{id}/export` +
  `POST /apps/import` ; Données `GET|POST /apps/{id}/export|import`). Volume `apps_exportees:/export`
  monté sur le Cœur (`EXPORT_DIR`).
- **Dashboard** : carte de livraison `livree` → bouton **« Décrocher · mettre de côté »** ; carte
  `decrochee` → badge **« De côté »**, chemin du dossier, bouton **« Reprendre pour modifier »**.
- **Preuve E2E (aller-retour réel sur Menuiserie Lefèvre & Fils)** : état initial 4 docs + 1 audit +
  1 app + 6 enregistrements (chantier/commande_de_bois/devis : 2/2/2). **Décrocher** → dossier écrit
  (`dossier.json` 90 Ko + `app.html` 56 Ko + LISEZMOI), et **toutes les briques répondent 404/vide**
  (sortie réelle vérifiée), statut `decrochee`. **Reprendre** → **mêmes ids** restaurés (docs/audit/app
  HTTP 200, données 2/2/2, `_id` & `_cree` d'origine inchangés), statut `livree`. **Re-décrocher** →
  fonctionne à nouveau (cycle répétable). Round-trip prouvé sans perte d'identité.

**Limite assumée (dette → évolution)** : l'**espace de messagerie Oria/Matrix n'est pas supprimé** au
décrochage (suppression d'un world Matrix lourde/risquée) — ses refs restent dans le dossier, la
messagerie continue de fonctionner ; nettoyage Oria = évolution. Pas d'auth sur `/usine/*` (réseau
dev). Le dossier portable n'est pas (encore) ré-importable sur **une autre** instance Workplace —
il sert l'aller-retour sur la même solution.

#### ✅ S7 v1 livré — l'assistant du Cœur (« Jarvis ») pilote l'usine en langage naturel (2026-06-05)
Le Cœur n'est plus seulement piloté par boutons/API : il a un **assistant conversationnel** qui
**agit vraiment** (Objectif 2). Modèle repris de `workspace/assistant` (agent ReAct : boucle LLM ↔
outils, fallback de modèles), adapté à l'architecture Workplace.

- **Agent** (`core/assistant.py`) : boucle ReAct (max 6 itérations) sur le **Gateway déjà utilisé par
  les briques** (compatible OpenAI, function-calling, `gpt-4o-mini`). Émet un **flux d'événements SSE**
  (texte / appel d'outil / résultat / fin). Bascule de modèle si le primaire est indisponible.
- **Outils** (`core/outils_usine.py`) : chaque capacité = une spec function-calling + un répartiteur
  `executer(nom, args)` qui appelle les **fonctions internes existantes** du Cœur (orchestrateur,
  cycle de vie) — aucune logique métier réécrite. *Lecture* : `lister_entreprises`,
  `details_entreprise`, `etat_briques`. *Action* : `livrer_entreprise`, `decrocher_entreprise`,
  `reprendre_entreprise`.
- **Garde-fou confirmation** : les outils d'action **refusent de s'exécuter** tant que `confirme=true`
  n'est pas passé ; sans lui, ils renvoient au modèle une `confirmation_requise` qu'il reformule à
  l'utilisateur. Le prompt système interdit au modèle d'inventer `confirme=true` → toute action
  destructrice (décrocher retire des bases centrales) passe par un **accord explicite**.
- **Endpoint + UI** : `POST /assistant/chat` (SSE) + **3ᵉ onglet « Assistant »** du dashboard (chat
  avec bulles, pastilles d'appel d'outil colorées lecture/action/confirmation, lecture du flux en
  streaming via `fetch`/`ReadableStream`). Une action rafraîchit le tableau « Usine » en arrière-plan.
  Config : `GATEWAY_URL`/`GATEWAY_KEY`/`GATEWAY_MODEL` ajoutés au compose du Cœur.
- **Preuve E2E (API)** : (1) *« Où en sont les entreprises ? »* → appelle `lister_entreprises`, répond
  juste (Menuiserie décrochée). (2) *« Reprends la Menuiserie »* → **demande confirmation et n'agit
  pas** (statut inchangé). (3) *« Oui je confirme »* → appelle `reprendre_entreprise(confirme=true)` →
  **exécuté** : statut `livree`, app HTTP 200, données 2/2/2 restaurées.

**Limite assumée (dette → évolution)** : pas de streaming token-par-token (réponse par message complet
à chaque tour) ; historique outils reconstruit à chaque requête (le client ne renvoie que user/assistant) ;
pas de persona/RAG/voix (présents dans `workspace/assistant`, hors périmètre v1) ; `/assistant/*` sans
auth (réseau dev).

#### ✅ S8 v1 livré — l'assistant sert toute la solution + une vraie mémoire (2026-06-05)
Deux évolutions : l'assistant n'est plus cantonné à l'usine (il couvre **toutes les briques**,
lecture **et** actions gardées par confirmation), et la solution gagne une **mémoire persistante**
en intégrant le projet **Memory** (`~/Desktop/Memory`) comme brique.

- **Mémoire = brique `memoire`** (port 5600, au registre). Le projet Memory (FastAPI + Postgres/
  pgvector, graphe de souvenirs, stages IPCRa, tiers, recherche hybride) est **enveloppé par un
  adaptateur** (`briques/memoire/main.py`) qui expose un contrat simple et français — `POST /retenir`,
  `GET /rappeler`, `GET /souvenirs`, `GET /sante` — et masque la complexité (compte de service, JWT,
  espace par défaut « Workplace »). Un seul `docker compose` démarre Postgres+pgvector, le backend
  Memory (Dockerfile ajouté côté Memory) et l'adaptateur. Memory laissé quasi intact (2 correctifs
  d'infra : `bcrypt==4.0.1` pour compat passlib ; SQL `CAST(:embedding AS vector)` au lieu de
  `:embedding::vector` qui cassait la recherche sous asyncpg). Extension `vector` activée par un
  script d'init Postgres.
- **Assistant élargi** (`core/outils.py`, ex-`outils_usine.py`) : *lecture* sur toute la solution —
  `lister_entreprises`, `details_entreprise`, `etat_briques`, `chercher_documents`, `lire_document`,
  `lister_apps`, `consulter_donnees`, `memoire_rappeler` ; *actions* (confirmation obligatoire) —
  `livrer/decrocher/reprendre_entreprise`, `ingerer_document` (ETL), `creer_enregistrement` (Données),
  `memoire_retenir`. Le prompt système annonce la mémoire (rappeler au besoin, retenir ce que
  l'utilisateur veut garder) et renforce la règle de confirmation (un « oui » explicite → `confirme=true`
  immédiat).
- **Preuve E2E (API)** : (1) brique mémoire — `retenir` puis `rappeler` (le souvenir pertinent ressort
  premier) ; (2) assistant lecture cross-brique — « quelles applications ont été générées ? » → appelle
  `lister_apps` (Générateur) et répond ; (3) assistant mémoire — « mémorise ma préférence… » →
  **confirmation demandée**, puis « oui je confirme » → `memoire_retenir(confirme=true)` → **souvenir
  réellement persisté dans Memory** (3 nœuds en base) ; (4) « qu'est-ce que tu sais sur mes préférences ? »
  → `memoire_rappeler` → réponse synthétisée depuis la mémoire. L'assistant **se souvient entre
  conversations**.

**Recherche sémantique réelle (complété ce jour)** : l'embedder de Memory est **branché sur le
Gateway** → embeddings `all-MiniLM` (Ollama local, **384 dims**, exactement la colonne `Vector(384)`),
gratuits et rapides sur CPU. Ajouté au Gateway : modèle `embedding/all-minilm` (→ `ollama/all-minilm`)
+ `litellm_settings.drop_params: true` (le client OpenAI envoie `encoding_format=base64`, refusé par
Ollama). Memory pointé via `LLM_PROVIDER=openai` + `LLM_BASE_URL=…:4001/v1` +
`EMBEDDING_MODEL=embedding/all-minilm`. **Prouvé** : recherche sémantique « argent que doit un
client » (0 mot en commun avec les souvenirs) → « Facture impayée juin » ressort 1ʳᵉ (score 0,56 vs
~0,30) — scores variés, fini le 1.000 dégénéré du mode dégradé. Repli automatique sur l'embedder
dégradé si le Gateway tombe.

**Limite assumée (dette → évolution)** : `all-MiniLM` est un petit modèle (ranking modeste sur les
requêtes ambiguës) — un modèle d'embedding plus fort affinerait. Les souvenirs créés AVANT ce
branchement gardent leurs vecteurs dégradés (pas de ré-indexation). Le « Jardinier » LLM de Memory
est désactivé (`GARDIEN_DEFAULT_MODE=off`). Mémoire mono-espace (« Workplace ») et sans auth côté
adaptateur (réseau dev). La conservation de l'historique outils entre tours reste côté modèle (cf. S7).

### 📦 Export & emplacement des applications générées

- **Générer (mode hébergé)** : `POST http://localhost:5400/generer` avec `{"audit_id":"…","persistance":"hebergee"}`
  → l'app utilise la brique `donnees` (port 5500, démarrer `cd briques/donnees && make up`). Sans le champ
  `persistance` (ou `"autonome"`), l'app reste en localStorage (1 fichier, mono-poste).
- **Générer avec messagerie (S3)** : ajouter `"messagerie":true` (défaut en hébergé) →
  `{"audit_id":"…","persistance":"hebergee","messagerie":true}`. Le générateur provisionne un espace Oria
  (world + 1 salon / bounded_context) et embarque l'onglet « Messagerie » (SSO Keycloak). Pré-requis :
  stack Oria up (backend 8000, dendrite 8010, keycloak 8081) + client `workplace-provisioner` dans le realm.
- **Lister les apps** : `GET http://localhost:5400/apps`
- **Aperçu navigateur** (sans téléchargement) : `http://localhost:5400/apps/{id}/apercu`
- **Télécharger le HTML** : `http://localhost:5400/apps/{id}/html`
- **Exporter sur disque** (fichier simple) : `POST http://localhost:5400/apps/{id}/exporter`
  → écrit `index.html` + `LISEZMOI.txt` dans **`~/Desktop/Workplace/apps_exportees/<entreprise>/`** (volume monté).
- **Packager un déploiement reproductible (S4)** : `POST http://localhost:5400/apps/{id}/packager`
  (corps optionnel `{"port_app":8090,"port_donnees":5510,"port_keycloak":8095}`) → écrit un **bundle
  Docker autonome** dans **`~/Desktop/Workplace/apps_exportees/<entreprise>-deploiement/`** : **3 services**
  — `identite` (**Keycloak propre au client**, realm `client-<slug>` pré-provisionné, comptes isolés,
  admin-only) + `donnees` (persistance dédiée) + `web` (l'app nginx). **Toute l'app est protégée par
  login** (PKCE contre le Keycloak du bundle). La réponse renvoie le mot de passe **admin** initial
  (temporaire) ; le LISEZMOI explique comment l'admin du client crée les comptes des employés.
  Livraison : copier le dossier chez le client puis `docker compose up -d --build` (Keycloak ~30-60 s
  au 1ᵉʳ démarrage). Pré-requis côté générateur : la source `briques/donnees` montée (`/briques_src/donnees`).
- Stockage interne : SQLite dans le volume Docker `generateur_data` (`/data/apps.db`).

> Règle : on ne passe à l'étape suivante qu'une fois la précédente **prouvée en marche**.

### ✅ Auth des apps livrées — les 2 limites levées (S13 + S14)

> Les apps livrées embarquent **leur propre Keycloak** (annuaire isolé, app gardée par login PKCE —
> cf. journal 2026-06-05). Les **deux** limites qui restaient pour une isolation **complète** (pas
> seulement à l'interface) sont désormais **levées et prouvées E2E** : **S13** (enforcement JWT réel
> sur `donnees`) et **S14** (Oria fait confiance au realm du bundle, login unique app + messagerie).

| Sprint | Objectif | Pourquoi | Statut |
|---|---|---|---|
| **S13 — Enforcement JWT côté `donnees`** | La persistance **valide le token Keycloak** du bundle : l'API refuse tout accès non authentifié, pas seulement l'UI. | L'app était gardée à l'écran mais `donnees` répondait sans vérifier → un accès direct à l'API contournait le login. | ✅ **livré** (2026-06-06, E2E réel) |
| **S14 — Messagerie isolée par client (Oria ↔ realm du bundle)** | La messagerie marche **sur le Keycloak du bundle** : Oria fait confiance au realm `client-<slug>`, login unique app + messagerie. | « Tout sur le Keycloak du bundle » (choix acté) : Oria ne validait que le realm central `oria` → token du bundle rejeté. | ✅ **livré** (2026-06-06, E2E réel) |

#### ✅ S13 — Enforcement JWT côté `donnees` (la persistance exige le login) — **LIVRÉ**

**Problème (résolu).** `briques/donnees/main.py` servait tous les endpoints `(app_id, entite_id)` **sans auth**,
CORS `*`. La garde du gabarit gate l'UI et **envoie déjà le `Authorization: Bearer`**, mais `donnees` l'ignorait
→ l'API restait ouverte à qui l'appelait en direct. Désormais l'enforcement est **réel côté serveur**,
**config-driven** pour ne pas casser le stack central (qui tourne sans auth).

- **Validation JWT dans `donnees`** : `briques/donnees/auth.py` (cache JWKS TTL + `verify_aud` conditionnel,
  **self-contained** — le bundle n'embarque pas le module partagé du workspace). Deps ajoutées au
  `requirements.txt` : `python-jose[cryptography]==3.3.0`, `httpx==0.27.0`. Dependency FastAPI `garde_auth`
  posée sur **les 9 routes de données** (`lister`/`creer`/`modifier`/`supprimer`/`seed`/`export`/`import`/`resume`/`purger`) ;
  **`/sante` reste publique** (sondes Docker).
- **Pilotée par l'environnement** (rétrocompat **totale**) : `AUTH_ENABLED` (défaut `false`), `KEYCLOAK_URL`,
  `KEYCLOAK_REALM`, `KEYCLOAK_AUDIENCE` (vide ⇒ `verify_aud` off), `JWKS_TTL`, `CORS_ORIGINS`. `AUTH_ENABLED=false`
  → comportement actuel inchangé (le `donnees` central de dev, port 5500, ne change pas). Log de démarrage
  honnête (ACTIVE / désactivée / ⚠ mal configurée = ouverte).
- **Câblage par le packager** (`generateur/packager.py`) : le service `donnees` du bundle reçoit
  `AUTH_ENABLED=true`, `KEYCLOAK_URL=http://identite:8080` (réseau interne du compose → JWKS), `KEYCLOAK_REALM=client-<slug>`,
  `CORS_ORIGINS=http://localhost:<port_app>` (au lieu de `*`), et **`depends_on: identite`**. La validation est
  par **signature + expiration** (l'`issuer` navigateur `localhost:<port_keycloak>` ≠ URL interne est sans
  incidence : seules les clés du realm comptent, l'issuer n'est pas contrôlé en v1). `auth.py` ajouté à la liste
  des fichiers copiés + au manifeste du récap.
- **Prouvé E2E (Docker réel, 2026-06-06)** : Keycloak 26.2.5 + realm de test, **vrai** token utilisateur via ROPC.
  Matrice **10/10** contre l'app `donnees` réelle — enforce : POST/GET/DELETE **sans** token → **401**, token
  **forgé** → 401, **vrai** token → **201/200/204** (CRUD complet) ; `/sante` → 200 ; ouvert (AUTH off) : POST/GET
  sans token → 201/200 (**régression nulle**). Incident révélateur honnêtement tracé : un redémarrage de Keycloak
  en cours de test a fait diverger le **cache JWKS** (TTL 600 s) → « signature verification failed » sur token
  pourtant valide ; cache vidé (redémarrage `donnees`) → 10/10. **Le cache fonctionne comme prévu** ; en prod le
  realm ne tourne pas ses clés à chaud.
- **Dette restante** : l'app doit **rafraîchir/renvoyer** le token sur 401 (la garde du gabarit gère l'expiration
  côté UI — à relier à un retry du Store) ; audience non exigée par défaut (tokens PKCE publics : `azp=app`, pas
  forcément `aud`) ; `issuer` non vérifié (acceptable tant qu'un seul realm de confiance par bundle).

#### ✅ S14 — Messagerie isolée par client (Oria fait confiance au realm du bundle) — **LIVRÉ**

**Problème (résolu).** Le widget messagerie réutilise déjà `__WP_TOKEN` (le jeton du client `app` du bundle),
mais le backend **Oria** validait en **mono-realm** (`routers/auth.py` : `KeycloakSettings(realm=oria, audience=oria-app)`)
→ un token du realm `client-<slug>` était **rejeté** (`Invalid audience` / mauvais realm). Oria accepte désormais,
**en plus** du realm central, les realms des bundles de confiance — **sans** dupliquer la pile Oria/Matrix par livraison.

- **Option retenue = C (Oria multi-realm, infra messagerie centrale, identité du client).** Oria garde **une**
  instance ; le *contenu* reste cloisonné par **world/espace** (un par entreprise) ; seule l'**identité** devient
  celle du client. (A — Oria-par-bundle : trop lourd ; B — fédération Keycloak : double login — écartées.)
- **Découverte qui simplifie** : le widget réutilise le jeton du client **`app`** (pas besoin d'un 2ᵉ client
  `oria-app` dans le realm du bundle, contrairement au plan initial → **moins invasif**, rien à changer au packager).
- **Oria multi-realm** (`oria-stack/oria/backend/routers/auth.py`, mirroré dans `workspace/oria`) : `get_current_user`
  **résout `KeycloakSettings` selon l'`issuer` du jeton** (`jwt.get_unverified_claims` → realm), cache `KeycloakSettings`
  par `(base, realm)`. **Allowlist** `KEYCLOAK_REALMS_AUTORISES` avec motif suffixe `*` (défaut **`client-*`** →
  tous les bundles de confiance sans reconfigurer Oria par livraison) ; le realm central est toujours autorisé.
  Realm de bundle → `audience=""` (`verify_aud` off, le jeton vient du client `app`) ; realm central → `_KC`
  **inchangé** (audience `oria-app`). `admin.py` (rôle admin) reste sur le realm central. **Anti-SSRF** : les JWKS
  ne sont récupérées que depuis une **base d'émetteur de confiance** (`KEYCLOAK_ISSUERS_AUTORISES`, défaut = KC
  central) ; un `iss` forgé pointant ailleurs retombe sur le KC central.
- **Provisioning** : inchangé — l'utilisateur du bundle est **auto-provisionné** par Oria au 1ᵉʳ `/api/auth/me`
  (id = `sub` Keycloak, identité Matrix `@oria_<sub>:oria.local`) puis rejoint le world via `/rejoindre` (le world
  est créé à la génération par `oria_provisioning.py`, service account central).
- **Prouvé E2E (stack Oria réelle en cours, Docker, 2026-06-06)** : 2 realms créés dans le KC central + vrais tokens
  ROPC. Matrice **4/4** sur `GET /api/auth/me` : realm de bundle `client-e2etest` (matche `client-*`) → **200**
  + **identité Matrix provisionnée** ; realm non listé `autretest` → **401 « Realm non autorisé »** ; sans token /
  token bidon → **401** ; **régression** realm central `oria` (vrai client `oria-app`, `aud=oria-app`) → **200**.
  Objets de test nettoyés (realms supprimés, `oria-app` remis `directAccessGrants=false`).
- **Dette restante / honnêteté** : (1) **KC de bundle physiquement séparé** — la logique « JWKS depuis la base de
  l'`iss` » existe mais l'E2E a utilisé un realm **co-localisé** sur le KC central ; un vrai bundle à KC distant
  exige `KEYCLOAK_ISSUERS_AUTORISES=<base joignable>` + réseau ouvert (knob en place, **pas encore prouvé** avec un
  KC séparé). (2) **Unicité cross-realm** : l'id Oria = `sub` (UUID, collision négligeable) mais le **relink par email**
  pourrait fusionner un compte central et un compte de bundle de même email → à cloisonner si besoin (dette assumée).
  (3) **E2EE** des salons toujours hors périmètre (cf. dette S3). (4) Envoi/persistance d'un message Matrix de bout en
  bout (widget → salon) non rejoué ici au navigateur — l'identité Matrix est provisionnée et le flux `/rejoindre`
  inchangé depuis S3 (prouvé alors).

---

## 7. Décisions actées (journal)

| Date | Décision |
|---|---|
| 2026-06-02 | Nom du projet : **Workplace**. |
| 2026-06-02 | Mémoire = **MemPalace** réutilisé tel quel ; concept nommé « **Mémoire** », pas « Conscience ». |
| 2026-06-02 | Cœur inspiré du **principe** de Gungnir (plugins + versioning), **sans** copier son code (BSL) ni son nom. |
| 2026-06-02 | **Oria** sert double : messagerie interne livrée aux entreprises + collaboration de Workplace. |
| 2026-06-02 | Principe ⭐ : **ajout de nouvelles briques à tout moment** via registre + manifest. |
| 2026-06-02 | Avancement **brique par brique** ; « code existe » ≠ « ça tourne ». |
| 2026-06-02 | Cœur Workplace v0.1.0 **opérationnel** sur port 5100. 6 manifests chargés, santé-globale confirme Gateway ok. |
| 2026-06-02 | **Brique ETL** v0.1.0 opérationnelle sur port 5200. Ingestion PDF/Word/Excel/images/HTML + stockage SQLite. 7 briques dans le registre. |
| 2026-06-02 | **Oria branchée** — 10 containers healthy. Frontend port 3003 (3002 réservé à fleuriste). Backend `/health` confirmé ok depuis le Cœur. |
| 2026-06-02 | Dashboard visuel ajouté au Cœur — `http://localhost:5100/dashboard` (actualisation auto toutes les 30s). |
| 2026-06-02 | **Brique Audit** v0.1.0 opérationnelle sur port 5300. 4 couches LLM (Territoire/Flux/Problèmes/Priorités), audit asynchrone, SQLite. |
| 2026-06-02 | **Brique Générateur** v0.1.0 opérationnelle sur port 5400. Plan LLM + template Bootstrap 5 HTML. Pipeline ETL→Audit→Générateur prouvé. 9 briques dans le registre. |
| 2026-06-03 | **Vertical slice complet prouvé** (étape 9). Entreprise test « Menuiserie Lefèvre & Fils » : 4 docs → audit 4 couches → dashboard HTML sur-mesure « MenuiseriePilot ». |
| 2026-06-03 | **Constat matériel** : Mac Intel sans GPU → Ollama local trop lent (3min20/appel). LLM des briques routé via **OpenRouter** (Gateway). |
| 2026-06-03 | Clé OpenRouter renouvelée (l'ancienne renvoyait 401 « User not found »). `docker compose restart` ne relit pas `.env` → recréer le conteneur (`up -d --force-recreate`). |
| 2026-06-03 | **Robustesse LLM** : retry + backoff exponentiel (respecte `Retry-After`) sur 429/503 ajouté dans `gateway.py` d'Audit et Générateur. `gabarit.py` rendu défensif (helpers `_d`/`_l`) — ne plante plus si le JSON LLM renvoie une liste là où un dict est attendu. |
| 2026-06-03 | Modèles **gratuits** OpenRouter trop instables pour l'enchaînement (503/429/lenteur). Slice finalisé sur **`openai/gpt-4o-mini`** (cheap, fiable, 2s/appel). |
| 2026-06-03 | **App opérationnelle (étape 10, en cours)** : Générateur → modules CRUD interactifs (localStorage) + Pareto CA×Temps×Pénibilité + vue « Application proposée » (modules + MoSCoW). Le livrable n'est plus un dashboard d'audit mais une vraie app. |
| 2026-06-04 | **Sprint S2 livré** : nouvelle brique **`donnees`** (Persistance, port 5500) — magasin CRUD générique multi-tenant (SQLite, IDs serveur stables, CORS ouvert). Le Générateur livre désormais en **deux modes** : *autonome* (localStorage, défaut) et *hébergé* (persistance serveur partagée). **Édition** des enregistrements ajoutée. Prouvé bout-en-bout au navigateur (Playwright) + brique conteneurisée. 10 briques au registre. |
| 2026-06-04 | **Sprint S4 v1 livré** : déploiement **reproductible**. Le Générateur (v0.2.0) **empaquette une app en bundle Docker autonome** par entreprise (`POST /apps/{id}/packager`) : `docker-compose.yml` (nginx + brique `donnees` **dédiée**, bâtie sur place) + `web/{index.html,config.js}` + `seed.json` + LISEZMOI → lancé d'un `docker compose up -d --build`. **Multi-tenant par déploiement** (persistance isolée du stack de dev), **config runtime** via `window.WP_CONFIG` (le même HTML se déploie partout), **auto-seed** idempotent de la brique `donnees` (`SEED_FILE`). Prouvé E2E (Playwright) : bundle Menuiserie servi sur :8090 ↔ sa propre persistance :5510, enregistrement créé **survit au rechargement** et **absent** du `donnees` central → isolation réelle. Dette assumée : auth Keycloak gating de **toute** l'app = évolution (réutilisera l'OIDC PKCE de S3). |
| 2026-06-04 | **Sprint S5 v1 livré** : le **Cœur (v0.2.0)** devient l'**orchestrateur de l'usine**. `core/orchestrateur.py` enchaîne ETL→Audit→Génération(→Packaging) **en une commande** (`POST /usine/livrer`, multipart) en pilotant les briques par leurs **contrats HTTP** (URLs résolues depuis le registre), avec **polling des étapes async** et erreurs attribuées à leur étape. **Tableau des entreprises livrées** persisté (SQLite, volume `core_data`) + endpoints `GET /usine/livraisons[/{id}]`, `DELETE`. Dashboard du Cœur enrichi d'un onglet **« Usine à apps »** (formulaire de livraison + progression visuelle par étape + liens aperçu/HTML). Prouvé E2E (Playwright) : Menuiserie livrée en une commande (4 docs → app **MenuiserieOps** servie + bundle Docker), livraison **persistée au redémarrage**. Dette : pas de retry/annulation par étape, `/usine/*` sans auth (réseau dev). |
| 2026-06-05 | **S8 — Memory déplacé dans la brique** : le projet Memory (`~/Desktop/Memory`) est désormais **inclus dans Workplace** sous `briques/memoire/memory/` (backend + frontend + cli + mcp ; venv jeté). Le `docker-compose.yml` de la brique bâtit le backend par chemin **relatif** (`./memory/backend`) → brique **autonome**, plus de dépendance à un chemin absolu hors-projet. `.dockerignore` ajouté pour que l'image de l'adaptateur n'embarque pas tout le projet. Rebâti et re-vérifié : santé OK, **9 souvenirs conservés** (volume intact), recherche sémantique toujours réelle. |
| 2026-06-05 | **S8 — nettoyage** : retrait de l'ancienne mémoire **mempalace** (remplacée par la brique `memoire`/Memory) et du stub mort **`briques/assistant`** (ETL/OCR jamais activé). Supprimés : `briques/mempalace/`, `briques/assistant/`, données `~/Desktop/.workplace-mem/` (→ corbeille), clé virtuelle `sk-mempalace` du Gateway. Registre : 11 → **9 briques**. Gateway et brique mémoire re-vérifiés sains. |
| 2026-06-05 | **S8 — recherche sémantique réelle de la mémoire** : l'embedder de Memory branché sur le **Gateway**. Ajout au LiteLLM du modèle `embedding/all-minilm` (→ Ollama `all-minilm`, **384 dims** = colonne `Vector(384)`) + `drop_params: true` (le client OpenAI envoie `encoding_format=base64`, refusé par Ollama). `briques/memoire` (backend Memory) pointé sur le Gateway pour les embeddings. Prouvé : requête « argent que doit un client » (0 mot commun) → « Facture impayée juin » 1ʳᵉ (0,56 vs ~0,30) ; fini le score 1.000 dégénéré du mode dégradé. Repli auto si Gateway down. |
| 2026-06-05 | **Sprint S8 v1 livré** : **assistant de toute la solution + mémoire persistante**. (1) Le projet **Memory** (`~/Desktop/Memory`) devient la brique **`memoire`** (port 5600) via un **adaptateur** (`briques/memoire/`) exposant un contrat simple `retenir`/`rappeler`/`souvenirs` ; un seul compose lance Postgres+pgvector + backend Memory + adaptateur (Memory quasi intact : fix `bcrypt==4.0.1`, fix SQL `CAST(:embedding AS vector)`, extension vector via init). (2) L'assistant (`core/outils.py`) couvre désormais **toutes les briques** — lecture (entreprises, documents ETL, apps, données, mémoire, santé) et actions gardées par confirmation (livrer/décrocher/reprendre, ingérer un doc, créer un enregistrement, **retenir un souvenir**). Prouvé E2E (API) : retenir→rappeler sur la brique ; assistant lit `lister_apps` ; assistant mémorise (après confirmation) → **persisté dans Memory** ; assistant rappelle ses souvenirs. L'assistant **se souvient entre conversations**. Dette : embeddings Memory dégradés (recherche surtout textuelle), Jardinier off, mémoire mono-espace. |
| 2026-06-05 | **Sprint S7 v1 livré** : **assistant du Cœur (« Jarvis »)** — agent conversationnel qui **pilote l'usine**. `core/assistant.py` (boucle ReAct sur le Gateway, function-calling, fallback modèles, flux SSE) + `core/outils_usine.py` (outils lecture `lister_entreprises`/`details_entreprise`/`etat_briques` + actions `livrer`/`decrocher`/`reprendre`, appelant les fonctions internes existantes — aucune logique réécrite). **Garde-fou** : toute action exige `confirme=true` → demande de confirmation explicite avant d'agir. Endpoint `POST /assistant/chat` (SSE) + **3ᵉ onglet « Assistant »** au dashboard (chat streaming, pastilles d'outils). Inspiré de `workspace/assistant` (agent/tools/chat). Prouvé E2E (API) : question d'état → outil + réponse juste ; « reprends la Menuiserie » → **confirmation demandée, pas d'action** ; « oui je confirme » → `reprendre(confirme=true)` exécuté (statut `livree`, app 200, données 2/2/2). Réalise l'**Objectif 2** : l'assistant n'assiste pas seulement, il **agit**. Dette : pas de streaming token-par-token, ni persona/RAG/voix, `/assistant/*` sans auth. |
| 2026-06-05 | **Sprint S6 v1 livré** : **cycle de vie des entreprises** (décrocher / reprendre). `core/cycle_de_vie.py` rassemble l'état éparpillé d'une entreprise livrée (docs ETL, audit, app+HTML+refs Oria, données) dans un **dossier portable** (`apps_exportees/<slug>-dossier/dossier.json` + `app.html` + LISEZMOI, format `workplace-dossier-v1`) **puis la retire vraiment** des bases centrales → la solution principale reste propre (`POST /usine/livraisons/{id}/decrocher`, statut `decrochee`). **Reprendre** (`…/reprendre`) réinjecte le dossier **à l'identique** (tous les ids préservés via `INSERT OR REPLACE`) pour la modifier, puis re-décrochable — **aller-retour sans perte**. Pattern « noyau + briques » : le Cœur n'orchestre que des **contrats export/import** ajoutés à ETL/Audit/Générateur/Données (aucune logique métier réécrite). Dashboard : boutons « Décrocher · mettre de côté » / « Reprendre pour modifier ». Prouvé E2E (API) sur Menuiserie : 4 docs + audit + app + 6 enregistrements → décroché (briques **404/vide**, dossier 90 Ko écrit) → repris (**mêmes ids**, données 2/2/2, `_id`/`_cree` intacts) → re-décroché (cycle répétable). Dette assumée : world Oria/Matrix non supprimé au décrochage (refs conservées, messagerie continue) ; dossier non ré-importable sur une autre instance ; `/usine/*` sans auth. |
| 2026-06-04 | **Sprint S3 livré** : l'app hébergée embarque la **messagerie interne Oria**. Provisioning serveur d'un **espace (world) + 1 salon par bounded_context** via compte de service Keycloak `workplace-provisioner` ; **widget Matrix natif** dans l'app avec **SSO Keycloak (OIDC PKCE, client `oria-app` partagé)**. Prouvé E2E (Playwright) : login `menuiserie-demo` → 6 salons → message envoyé **et persisté dans Matrix** (vérifié serveur). Dette assumée : salons non chiffrés (E2EE = évolution via embed frontend Oria). Config : CORS Oria + redirect URIs `oria-app` ouverts à `localhost:5400`. |
| 2026-06-05 | **Cerveau réglable autonome** : le bouton « Enregistrer la clé » du panneau ⚙ Cerveau **recrée** désormais le conteneur Gateway au lieu de le redémarrer (Docker fige l'env à la création → un `restart` gardait l'ancienne clé et renvoyait 401). `config_assistant.recreer_gateway()`/`_recreer_conteneur()` réinjectent la clé fraîche dans l'`Env` et recréent à l'identique (image/montages/réseaux/healthcheck), avec filet de sécurité (renomme l'ancien en `*_old`, restaure si échec). Prouvé E2E : clé bidon → 401, vraie clé → assistant rappelle ses outils. |
| 2026-06-05 | **Sprint S11 v1 livré** : **mémoire cloisonnée (espaces)**. Le backend Memory isole déjà les `spaces` ; l'adaptateur (`briques/memoire/main.py`) ne fige plus un seul espace — il **résout/crée les espaces par nom** (`_token` + `_espace_id`, cache `_espaces`) et accepte un paramètre **`espace`** sur `retenir`/`rappeler`/`souvenirs` (défaut = « Workplace » = solution → aucune régression). Côté Cœur, les outils `memoire_retenir`/`memoire_rappeler` gagnent `espace` (`solution`|`perso` → mappe « Perso ») et le prompt distingue **deux mémoires** (solution vs perso). **Bug corrigé** : deadlock d'`asyncio.Lock` (résoudre le token AVANT de prendre le verrou d'espace). Prouvé E2E : fait perso retenu dans « Perso », **invisible** côté solution (qui garde ses 8 souvenirs) ; l'assistant route « retiens pour moi… » → `espace=perso`. |
| 2026-06-05 | **Sprint S12 v1 livré** : **assistant plus personnel — persona + proactif**. (1) **Persona** : `core/personas.py` (7 personnalités reprises de `workspace/assistant/persona.py` : défaut/mentor/expert/brainstorm/coach/concis/analyste = fragments de prompt système), persistée dans la config (`config_assistant.definir_persona`), **préfixée à chaud** au `PROMPT_SYSTEME`. Réglable dans ⚙ Cerveau (sélecteur + `POST /assistant/persona`). (2) **Proactif léger** (idée de `proactive.py`, SANS Redis/push) : `core/proactif.py` = boucle asyncio (lancée dans le `lifespan`, intervalle 5 min) qui produit des **rappels** dédoublonnés en SQLite (`/data/rappels.db`) — **RDV imminents** (<2 h, via l'agenda S10) et **documents non classés** (ETL S9). Endpoints `GET /assistant/rappels`, `POST /assistant/rappels/check` (déclenchement manuel), `POST /assistant/rappels/{id}/vu`. Front : **pastille 🔔** (compteur non-lus) + panneau (En parler / Vu). Prouvé E2E : persona « concis » réglée → réponse courte ; RDV créé à +1 h → rappel « Rendez-vous bientôt » ; « 10 documents à classer » ; « Vu » décrémente 🔔2→🔔1 ; dédoublonnage OK ; 0 erreur JS (Playwright). Toujours **un seul** assistant (le Jarvis enrichi). Hors périmètre : vault/OAuth/Google Agenda, prompts planifiés (cron), push/PWA. |
| 2026-06-05 | **Registre : ouvrir une brique** — chaque carte du registre a un bouton **« Ouvrir ↗ »** qui affiche un **panneau de détail** (santé live, description, offre, dépendances, port) avec l'**accès adapté** à ce que la brique expose vraiment : `agenda` → bascule sur l'onglet Agenda du dashboard (champ manifest `vue_dashboard`) ; `oria` → ouvre son appli `localhost:3003` (champ manifest `url_ui`) ; briques purement API (etl/audit/donnees/generateur/gateway/memoire) → **console Swagger `/docs`** ; toutes → lien **Santé** (dérivé de `url_sante`, `host.docker.internal`→`localhost`) ; `app-builder`/`forge` (sans port) → « non exposée ». Convention : 2 champs manifest optionnels — `vue_dashboard` (onglet interne) et `url_ui` (appli web). Vérifié au navigateur (agenda→onglet, oria→appli, 0 erreur JS). |
| 2026-06-05 | **Sprint S10 v1 livré** : **brique `agenda` + l'assistant gère les rendez-vous**. Rapatriement de `workspace/calendar` (même famille que Workplace) comme **brique `agenda`** (port 8400) — `briques/agenda/` vendorise `backend/` + la lib `shared/agent_personnel_shared`, Dockerfile à contexte local, SQLite (auth off → identité par en-tête **`X-User-Id: perso`**), Redis optionnel, santé `/health`. Côté Cœur : `core/agenda.py` (client, garantit un calendrier « Perso » par défaut) ; outils assistant `agenda_consulter` (lecture), `agenda_creer_evenement`/`agenda_deplacer_evenement` (**immédiats**, réversibles) et `agenda_supprimer_evenement` (confirmé) ; `assistant.py` **injecte la date/heure courante (Europe/Paris)** pour interpréter « demain 14h » → ISO 8601. `GET /agenda/evenements` (proxy) + **4ᵉ onglet « Agenda »** au dashboard (RDV à venir groupés par jour). `_etat_briques` sonde désormais l'`url_sante` du manifest (l'agenda est en `/health`). Lanceurs `.command` + registre = **10 briques**. Prouvé E2E : brique seule (calendrier+événement CRUD, X-User-Id) ; via l'assistant « ajoute un rdv demain 16h réunion équipe salle B » → **créé directement** à la bonne date (Dentiste + réunion visibles dans le proxy) ; onglet Agenda rendu sans erreur JS (Playwright). Garde le Jarvis actuel. Hors périmètre : couche assistant perso (`workspace/assistant`) + espace mémoire perso + Google Agenda + frontend React du calendar. |
| 2026-06-05 | **S9 — Unmute préparé (config-driven)** : le passage voix-navigateur → **Kyutai Unmute** est désormais une **simple configuration**. Back : config persistée enrichie de `voix_provider` (`webspeech`|`unmute`) + `unmute_url` (`config_assistant.definir_voix`, exposés par `GET /assistant/config`, réglés par `POST /assistant/voix`). Front : section **Voix** dans ⚙ Cerveau (sélecteur + URL, persistés) ; `VOIX` reconstruit à chaud (`construireVoix`) ; **`creerUnmute(url)` réel** (WebSocket `/v1/realtime` sous-protocole `realtime` ; `session.update` puis `input_audio_buffer.append` ; réceptions `response.text/audio.delta` + transcription ; audio **Opus 24 kHz mono base64 via WebCodecs**). Déploiement prêt **non lancé** : `outils/unmute/` (`docker-compose.override.yml` pointant le backend Unmute sur **notre Gateway** via `KYUTAI_LLM_URL`/`KYUTAI_LLM_API_KEY`/`KYUTAI_LLM_MODEL` et mettant le vLLM embarqué à 0 réplique, `.env.example`, `LISEZMOI.md` avec pré-requis GPU NVIDIA ≥16 Go/Linux). Vérifié : GET/POST voix persistent (aller-retour), front rend la section sans erreur JS, choisir « Unmute » révèle le champ URL. **Honnêteté** : audio Opus/handshake non testables sans GPU (marqués « à valider ») ; en mode Unmute, Unmute pilote la conversation (pas la boucle à outils) → mode brainstorming, le mode Navigateur garde les outils. |
| 2026-06-05 | **Registre : séparation Frontend / Backend** — chaque `manifest.json` porte désormais un champ **`couche`** (`frontend` \| `backend`), placé après `role`. Convention : **frontend** = brique qui présente une interface utilisateur (`oria` UI :3003, `app-builder` app HTML) ; **backend** = service API pur (`gateway`, `etl`, `audit`, `generateur`, `donnees`, `memoire`, `agenda`, `forge`). La vue « Registre de briques » du dashboard groupe les cartes en **deux sections titrées** (Frontend / Backend) avec compteur, chacune dans sa propre grille (`charger()` répartit par `couche`, repli sur `backend` si absent). NB : `oria` est full-stack (backend Matrix :8000 + UI :3003) → classé **frontend** car c'est l'app que l'utilisateur ouvre. Prouvé E2E : `GET /briques` sert `couche` (reload OK) ; Cœur rebâti ; dashboard rend **Frontend (2)** = app-builder+oria, **Backend (8)** = les autres (Playwright, 0 erreur JS). |
| 2026-06-05 | **Auth des apps livrées — Keycloak par bundle (annuaire de comptes isolé)** : chaque bundle livré (`POST /apps/{id}/packager`) embarque désormais **son propre serveur d'identité Keycloak** (3ᵉ service `identite`, image `quay.io/keycloak/keycloak:26.2.5`, volume `identite_data`) avec un **realm pré-provisionné `client-<slug>`** propre à l'entreprise — totalement isolé du stack central et des autres clients. Realm : client public **`app`** (OIDC **Authorization Code + PKCE S256**, redirect `http://localhost:<port_app>/*`), **inscription libre désactivée** (admin-only, choix retenu), 1 compte **`admin`** (rôle `realm-management:realm-admin` → il crée les comptes des employés via la console Keycloak) à **mot de passe temporaire** généré. **Toute l'app** est gardée derrière ce login : `gabarit.py` injecte une **garde d'auth** (overlay + flow PKCE maison, zéro dépendance) activée seulement si `window.WP_CONFIG.auth` est présent (bloc écrit dans `config.js` du bundle) → **mode autonome/dev inchangé** (rétrocompat). Le token est propagé aux appels `donnees` (prêt pour l'enforcement serveur) et **réutilisé par la messagerie** (`messagerie.py` lit `__WP_AUTH`/`__WP_TOKEN` → login unique). `main.py` : `DemandePackage.port_keycloak` (défaut 8095). Prouvé E2E (Docker réel) : bundle généré → `docker compose up identite` → realm importé (~30 s), OIDC live (issuer correct, PKCE S256), client `app` public+PKCE+redirect OK, `registrationAllowed=false`, admin avec `realm-admin` — vérifié via l'API admin Keycloak. Dette assumée : `donnees` ne **valide pas encore** le JWT (gating UI ; enforcement serveur = durcissement) ; pour que la **messagerie** marche 100 % sur ce realm, le serveur **Oria doit faire confiance** au realm du bundle (Oria-par-client ou fédération) — câblage prêt côté app, intégration Oria = évolution. |
| 2026-06-05 | **Sprint S9 v1 livré** : **voix temps réel + documents auto-classés**, connectés via l'assistant. (1) **Voix** (front, 0 infra) : boutons 🎤 (parler) et 🔊 (lecture des réponses) dans le chat, via **Web Speech API** (`SpeechRecognition` fr-FR + `speechSynthesis`), derrière une **abstraction de fournisseur** (`VOIX_PROVIDER`) — stub `UnmuteProvider` prêt pour **Kyutai Unmute** le jour d'un GPU (Moshi/Unmute exigent GPU NVIDIA ≥16 Go/Linux → impossible sur ce Mac Intel, constaté honnêtement). (2) **Documents** : dépôt par glisser-déposer/📎 → `POST /assistant/document` (Cœur) → ETL ingère → **classement LLM** (`core/classer.py` : catégorie, tags, entreprise rattachée→`livraison_id`, projet, résumé, JSON strict via le même cerveau que l'assistant) → rangé dans `metadonnees.classement` de l'ETL (**sans migration**). Nouveaux endpoints ETL `PATCH /documents/{id}/classement`, filtres `GET /documents?categorie|projet|entreprise_id`, `GET /dossiers` ; outils assistant `classer_document` (ACTION), `lister_dossiers`, filtres sur `chercher_documents` (corrige au passage un bug : la liste ETL est `{documents:[…]}`). Front : **carte de classement** (catégorie/tags/entreprise/projet/résumé + « Ajuster » / « Retenir en mémoire ») et **section 📂 Dossiers** (projets + catégories). (3) **Connexion** : un document relie ETL↔usine (entreprise) et se range dans un **projet** libre (ex. « prochain sprint ») → l'assistant devient l'endroit où se prépare le sprint. Prouvé E2E : facture test → classée `facture` / projet `prochain sprint` / entreprise `Menuiserie_Lefèvre_et_Fils` (bon `livraison_id`) ; persistée, filtrable, visible dans Dossiers ; l'assistant la **retrouve** via `chercher_documents`. Front vérifié (Playwright, 0 erreur JS). Dette : voix navigateur (Chrome/Edge/Safari ; reco Chrome via Google), STT non testable en headless ; écriture en Mémoire proposée (non auto). |
| 2026-06-06 | **Sprint S13 v1 livré** : **enforcement JWT côté `donnees`** — l'isolation des apps livrées n'est plus seulement à l'écran, l'**API refuse** tout accès non authentifié. Nouveau `briques/donnees/auth.py` **self-contained** (cache JWKS TTL + `verify_aud` conditionnel ; le bundle n'embarque pas le module partagé du workspace) ; deps `python-jose[cryptography]`/`httpx`. Dependency FastAPI `garde_auth` posée sur **les 9 routes de données** ; **`/sante` publique**. **Config-driven, rétrocompat totale** : `AUTH_ENABLED` (défaut `false`) + `KEYCLOAK_URL`/`KEYCLOAK_REALM`/`KEYCLOAK_AUDIENCE`/`JWKS_TTL`/`CORS_ORIGINS` → le `donnees` central de dev (port 5500) **inchangé**. Le **packager** câble le service `donnees` du bundle (`AUTH_ENABLED=true`, `KEYCLOAK_URL=http://identite:8080` réseau interne, `KEYCLOAK_REALM=client-<slug>`, `CORS_ORIGINS` resserré sur l'app, `depends_on: identite`) et copie `auth.py`. Validation par **signature + expiration** (l'`issuer` navigateur ≠ URL interne JWKS est sans incidence). **Prouvé E2E (Docker réel)** : Keycloak 26.2.5 + realm de test, **vrai** token via ROPC → matrice **10/10** sur l'app `donnees` réelle : sans token / token forgé → **401**, vrai token → **201/200/204** (CRUD), `/sante` 200 ; mode ouvert (AUTH off) → 201/200 (**régression nulle**). Incident tracé honnêtement : redémarrage Keycloak en cours de test → cache JWKS (TTL 600 s) divergent → « signature verification failed » sur token valide ; cache vidé → 10/10 (le cache fonctionne comme prévu). Lève la 1ʳᵉ des 2 dettes de l'auth des apps livrées (cf. 2026-06-05). Dette restante : retry du Store sur 401 (refresh token), audience/issuer non exigés en v1, **S14** (messagerie Oria sur le realm du bundle) toujours préparé. |
| 2026-06-06 | **Sprint S14 v1 livré** : **messagerie isolée par client — Oria fait confiance au realm du bundle** (lève la 2ᵉ et dernière dette de l'auth des apps livrées). Option **C** (Oria multi-realm, infra messagerie **centrale**, **identité du client**) : Oria garde une instance, le contenu reste cloisonné par world/espace, seule l'identité devient celle du client. `oria-stack/oria/backend/routers/auth.py` (mirroré dans `workspace/oria`) : `get_current_user` **résout `KeycloakSettings` selon l'`issuer`** du jeton, cache par `(base, realm)`, **allowlist** `KEYCLOAK_REALMS_AUTORISES` avec motif `*` (défaut **`client-*`** → tous les bundles sans reconfigurer Oria par livraison ; realm central toujours autorisé). Realm de bundle → `audience=""` (jeton du client `app`) ; realm central → `_KC` **inchangé** ; `admin.py` reste central. **Anti-SSRF** : JWKS uniquement depuis une base d'émetteur de confiance (`KEYCLOAK_ISSUERS_AUTORISES`, défaut = KC central), repli central si `iss` inconnu. **Simplification vs plan** : le widget réutilisant le jeton du client `app`, **aucun client `oria-app` à provisionner** dans le realm du bundle → packager **non modifié**. Utilisateur du bundle **auto-provisionné** au 1ᵉʳ `/api/auth/me` (id=`sub`, identité Matrix `@oria_<sub>`). **Prouvé E2E (stack Oria réelle, Docker)** : 2 realms dans le KC central + tokens ROPC → matrice **4/4** sur `/api/auth/me` : bundle `client-e2etest` (matche `client-*`) → **200 + identité Matrix provisionnée** ; realm non listé `autretest` → **401 « Realm non autorisé »** ; sans token / bidon → **401** ; régression realm central `oria` (vrai client `oria-app`) → **200**. Nettoyage complet (realms de test supprimés, `oria-app` remis `directAccessGrants=false`). Dette assumée : KC de bundle **physiquement séparé** (knob `KEYCLOAK_ISSUERS_AUTORISES` en place mais E2E fait sur realm co-localisé), unicité cross-realm (relink par email à cloisonner si besoin), E2EE hors périmètre, envoi Matrix bout-en-bout non rejoué au navigateur (flux `/rejoindre` inchangé depuis S3). **Les 2 limites de l'auth des apps livrées sont levées.** |
| 2026-06-06 | **S15 — Forge branché comme brique (palier 1)** : la brique `forge` n'était qu'un `manifest.json` (coquille) ; le vrai core (`workspace/forge`, ~28 400 lignes, FastAPI) **n'avait jamais tourné branché au Cœur** (« 🟡 à tester »). Constat de cadrage : Forge est une **plateforme** (etcd+Patroni+pgbouncer, Qdrant, Keycloak, netbird/coturn, ml-module, frontend — 11 services), pas une brique simple ; et son code **sait déjà parler à Workplace** (env `MEMOIRE_URL`/`GATEWAY_BASE_URL` présents). Choix **option A** (modèle Neovim, contrats HTTP) : ne lever que le **core**. `briques/forge/docker-compose.yml` (modèle `memoire`) = Postgres simple + le core (build `context: ../../../workspace`, `dockerfile: forge/core/Dockerfile`), **branché aux briques** : LLM via **Gateway** (`host.docker.internal:4001`, `openai/gpt-4o-mini`), mémoire via **Mémoire** (`5600`, espace « Workplace ») ; Qdrant/Keycloak/ml-module laissés vides (le `lifespan` du core est trivial → démarre sans schéma ni auth ; `/api/health` est pur). **Prouvé E2E** : build OK → `GET :8600/api/health` `{"status":"ok","module":"forge:core"}` ; `/health` interne `degraded:false`, postgres `ok` ; **depuis le conteneur** Forge→Gateway **200** + Forge→Mémoire renvoie l'espace « Workplace » ; **sonde live du Cœur** `GET /briques/forge/sante` → `{"nom":"forge","statut":"ok","code_http":200}`. Registre : Forge passe de coquille à **brique vivante**. **Dette assumée (paliers suivants)** : (palier 2) Forge appelable comme **outil** par l'assistant du Cœur — pas encore câblé ; (palier 3) **cycle agent/RAG fonctionnel** non prouvé — exige Keycloak + token + schéma DB migré + Qdrant ; Forge non **copié** dans Workplace (build pointe encore le `workspace/forge` voisin → dossier pas 100 % autonome contrairement à gateway/oria). |
| 2026-06-06 | **S15b — Workplace rendu self-contained (prêt pour `git init`)** : objectif = repo git où **tout** est dans `Workplace/`. Seules dépendances de build/runtime hors dossier identifiées par audit : (1) la brique `forge` buildait depuis `../../../workspace` ; (2) les lanceurs pointaient forge sur `../workspace/forge` (mauvais chemin **et** externe) ; (3) `app-builder` n'était qu'un manifest, son HTML vivait dans `~/Desktop/application de création d'application/`. Correctifs : **Forge vendorisé** (`rsync` de `workspace/forge`→`briques/forge/forge/` + `workspace/shared`→`briques/forge/shared/`, sans node_modules/dist/.git ; 95 fichiers .py du core + ml-module/frontend/keycloak conservés pour S17), compose `context:` `../../../workspace`→**`.`** + `.dockerignore` ajouté ; **HTML app-builder copié** dans `briques/app-builder/` ; **lanceurs corrigés** (`Lancer`/`Arrêter` → `$RACINE/briques/forge`, santé `:8600/api/health`) ; `chemin_source` des manifests (forge/gateway/oria/app-builder) repointés en intra-repo. **`.gitignore` racine** ajouté : exclut **tous les `.env`** (secrets : Gateway/OpenRouter/JWT/Keycloak — `.env.example` conservés), node_modules, dist, `__pycache__`, `.playwright-mcp/`, logs. **Prouvé** : rebuild Forge **depuis le contexte interne** → `:8600/api/health` ok + sonde Cœur `{"statut":"ok"}` ; audit refs sortantes = **vide** ; `git init` de contrôle → **820 fichiers** versionnables, **0 `.env`**, **0 node_modules**, **6 `.env.example`** gardés. gateway (image, pas de build) et oria-stack (contextes relatifs internes) étaient déjà autonomes. Reste cosmétique non bloquant : script Proxmox (`/opt/workspace` = chemin **distant** serveur, normal), captures `.playwright-mcp/` (ignorées). |
| 2026-06-06 | **Sprint S17 v1 livré — Forge fonctionnel de bout en bout (agents + RAG prouvés)** : le 🟡 « à tester » historique devient 🟢 **fonctionnel prouvé**. **Chantier 0 (verrou)** : (a) **schéma DB migré** — la source Drizzle `schema.ts` ayant disparu au cutover S136, `briques/forge/forge/core/scripts/init_db.py` crée le schéma depuis les modèles SQLAlchemy reflétés (`models/generated.py` + `manual.py`) via `create_all` idempotent ; service one-shot **`forge-migrate`** dans le compose (que `forge` attend en complétion). Prouvé : **87 tables** sur Postgres vierge, rejouable. (b) **auth de service** (voie 2 tranchée S16) — client **`forge-service`** (`client_credentials`) **persisté** dans `oria-realm.json` (secret via `${FORGE_SERVICE_SECRET}`, **pas en clair**), l'adaptateur `briques/forge/main.py` obtient/rafraîchit le token (cache + marge 30 s) et le présente en `Bearer` ; core pointé sur le Keycloak d'Oria (`:8081`, realm `oria`, `verify_aud` off). **Prouvé** : `GET :5700/agents` → **200** ; core sans token / token bidon → **401/401** (auth réelle) ; user de service provisionné en DB. **Chantier 1 (RAG)** : **Qdrant** ajouté au compose ; décision **S17-5** = réutiliser l'unique moteur d'embeddings de la **Gateway** (`embedding/all-minilm`, 384d, le même que la brique Mémoire) plutôt que réveiller le ml-module torch → `_embed_local` reroute le provider « local » vers la Gateway (`LOCAL_EMBED_MODEL`). **Bug corrigé** : `GATEWAY_API_KEY` retombait sur un faux défaut (interpolation compose `${LLM_API_KEY}` non résolue au parse) → la Gateway refusait les embeddings ; clé maître désormais via l'env_file racine. **Prouvé** : ingestion → collection `forge_local` **1 vecteur** (embeddings 200). **Chantier 2 (adaptateur)** : routes **`POST /rag/ingerer`**, **`GET /rag/chercher`**, **`POST /agent/lancer`** (auth de service, erreurs mappées en messages clairs) + route core **lecture seule** `GET /api/rag/search` (exposant `memory.get_context`, qui n'était pas montée en HTTP). **Prouvé** : ingérer → 200+id ; chercher → passage exact restitué ; agent → réponse cohérente, **LLM via Gateway 4001** (chat+embeddings 200 dans les logs). **Chantier 3 (assistant)** : outils `forge_rag_chercher` (lecture libre), `forge_rag_ingerer` + `forge_lancer_agent` (ACTIONS, `confirme=true`) activés dans `core/outils.py`/`assistant.py`. **Prouvé E2E** via `/assistant/chat` (pastilles d'outils, 0 stacktrace) : « cherche les congés dans Forge » → `forge_rag_chercher` sans confirmation, réponse juste (25 jours) ; « lance un agent… » → **confirmation demandée**, puis **exécution sur « oui »** (agent renvoie de vrais slogans). **Honnêteté** : avec **gpt-4o-mini**, le modèle sur-demande la confirmation de `forge_lancer_agent` et **n'exécute pas** sur « oui » (boucle sans poser `confirme=true`) — le gate échoue **SAFE** (jamais d'exécution non confirmée), et le même mécanisme exécute bien `memoire_retenir` ; avec **gpt-4o** l'agent s'exécute correctement → la limite est l'adhérence du petit modèle, pas l'implémentation. Recommandation : modèle ≥ gpt-4o pour le lancement d'agent fiable. **Chantier 4** : coûts visibles dans `/assistant/usage` (S138 réutilisé) ; **garde-fous dégradation prouvés** : Qdrant coupé → recherche dégrade vers le fallback brique Mémoire (200, pas de crash) ; core Forge coupé → adaptateur **503** message clair, assistant dit « Forge n'est pas en ligne … dégradé ». **Dette assumée** : frontend Forge complet (:3000) non intégré ; multi-tenant/E2EE/RGPD avancés hors périmètre ; netbird/coturn non requis ; autres routers Forge (CRM, ventures, SEO, facturation…) à prioriser ensuite selon la valeur commerciale ; preuve auth faite contre un Keycloak `:8081` (image/realm identiques à oria-stack ; prod = Keycloak d'Oria adossé Patroni). |
| 2026-06-06 | **Cerveau de l'assistant — défaut « gratuit d'abord, flash en repli » (cost-first)** : suite S17, le cerveau par défaut passe à une **chaîne** plutôt qu'un modèle unique. Principal = **`free/qwen3-next`** (gratuit, Qwen3-Next-80B via OpenRouter, function-calling OK) ; repli = **`deepseek/deepseek-v4-flash`** (payant, ~2 s, fiable). Le pipeline du Cœur (`llm_pipeline`) bascule sur **tout HTTP ≥ 400** (dont **429** rate-limit) → quand OpenRouter limite le gratuit, flash prend le relais. **Mesure clé** : un gratuit saturé **pend ~60 s** au lieu de renvoyer un 429 rapide → ajout dans `litellm_config.yaml` d'un modèle **borné** `free/qwen3-next` (`timeout: 12`, `num_retries: 0`, nommé hors du bloc AUTO-FREE pour survivre au sync) → fail-over en **~2 s** (429 rapide) ou **12 s** au pire. **Inversion sans code** : `fallback_models=[deepseek, free/qwen3-next]` contient les deux et le 1er est dédupliqué → choisir l'autre modèle dans **⚙ Cerveau** (POST `{model}` seul, le fallback est **préservé** par `definir_modele`) inverse l'ordre (deepseek-d'abord). Câblé en **défaut compose** (`GATEWAY_MODEL`+`FALLBACK_MODELS`) et en **config live** (volume). **Prouvé E2E** : « combien de jours de congés ? » → gratuit **429** (logs) → deepseek → `forge_rag_chercher` → réponse juste **en 6 s** ; bascule gratuit↔flash vérifiée dans les deux sens. **Honnêteté** : modèle gratuit chroniquement rate-limité (donc flash sert souvent — coût réel faible mais non nul) ; deepseek-v4-flash est payant (pas dans les `free/*`). |
| 2026-06-06 | **Cerveau — cascade auto (sélection auto des gratuits) + IA locale connectable** : (1) **Sélection auto** : `briques/gateway/sync_free_models.py` ne garde plus que les gratuits OpenRouter qui **supportent les outils** (`supported_parameters: tools`) **et** sont **texte** (`architecture.modality`), classés par contexte ; chaque entrée AUTO-FREE est **bornée** (`timeout: 10`, `num_retries: 0`) pour un fail-over rapide (les gratuits *pendent* ~60 s au lieu de 429 quand saturés — mesuré). Relancé à chaque démarrage Gateway → le « meilleur candidat » suit l'offre. (2) **Cascade** dans le Cœur : `config_assistant.chaine_modeles()` construit dynamiquement `[tête éventuelle] + [N meilleurs gratuits servis] + [repli payant]` (défaut N=3, repli `deepseek/deepseek-v4-flash`) ; `assistant.py` l'utilise ; `llm_pipeline` bascule sur tout HTTP ≥ 400 (429 inclus). Réglages `cascade_auto`/`repli_payant`/`cascade_free_n` (env + live + UI ⚙ Cerveau, case à cocher + chaîne affichée). **Choisir un modèle = le mettre en TÊTE** : vide → cascade pure (gratuits d'abord, défaut cost-first) ; deepseek → payant d'abord (inversion) ; `ollama/*` ou `local/llm` → **IA locale d'abord**. (3) **IA locale** : Ollama déjà câblé et **prouvé** (chat `ollama/gemma4:e4b` → « bonjour » via Gateway) ; ajout d'un modèle générique **`local/llm`** (OpenAI-compatible, `LOCAL_OPENAI_URL`/`LOCAL_API_KEY`, env compose + `.env.example`) pour **LM Studio** (`:1234/v1`) / **llama.cpp** (`:8080/v1`), inerte si URL vide. **Prouvé E2E** : cascade pure → `forge_rag_chercher` → réponse juste **en 8 s**, coût ~0 (un gratuit a répondu) ; composition de chaîne vérifiée pour tête vide / deepseek / ollama. **Honnêteté** : gratuits OpenRouter rate-limités → le repli payant sert quand même souvent ; un tour d'assistant complet sur Ollama gemma4 **CPU** est lent (préférer un petit modèle/GPU pour du local réactif). |
| 2026-06-07 | **Sprint S19 — Forge : frontend intégré au dashboard (SSO + tenant)** : la SPA riche de Forge (workspace/agents/RAG/ventures, `@forge/frontend`) devient **accessible depuis le dashboard du Cœur** sans rupture. **Chantier 0 (décision)** : intégration en **iframe / sous-route** — onglet **« Forge »** du dashboard (`:5100`) qui affiche la SPA servie par la brique (nginx). Flux SSO documenté **honnêtement** : le dashboard du Cœur est *sans login* (posture mono-service S7/S10), donc le « pas de second login » se tient **au niveau du realm `oria`** (la connexion Keycloak faite *dans* la SPA est le sign-on unique partagé avec la messagerie Oria), pas comme une passation silencieuse. **Chantier 1 (servir la SPA)** : **blocage réel levé** — `shared-ui` (dépendance de la SPA) n'était vendorisée que dans `oria-stack/` → copiée dans `briques/forge/shared-ui` (sinon le build échouait) ; **service `frontend`** ajouté au compose de la brique (port hôte `FORGE_FRONTEND_PORT:-3000`, `depends_on: forge healthy`) ; **Dockerfile** : `VITE_*` injectés au build ; **nginx.conf** proxy-fie `/api` **et** `/v1` (la SPA réécrit `/api`→`/v1/api`, S99) vers `http://core:8600` rendu joignable par un **alias réseau `core`** sur le service `forge` ; `core/main.py` : onglet + iframe à **chargement paresseux** (`FORGE_UI_URL` injecté au service via `.replace`), bouton « Ouvrir dans un onglet ↗ ». **Chantier 2 (SSO)** : SPA buildée pour realm **`oria`**, KC `:8081`, client public **`oria-app`** (porte déjà le mapper `aud: forge` de S18 → reste valide quand l'audience sera verrouillée live) ; `redirectUris`/`webOrigins` du client incluent déjà `:3000` ; refresh/expiration déjà gérés par la SPA (`useAuth.onTokenExpired` + `api.jsx updateToken(30)`). **Chantier 3 (tenancy/garde-fous)** : la SPA **hérite** des cloisons S18 (le core n'honore l'`X-Org-ID` que pour un membre, sinon repli org perso) ; masquage volontairement **minimal** — le core embarque **tous** les routers (≈28 400 lignes), il n'y a pas de routers « morts » ; les vraies dégradations sont **infra-dépendantes** (voix temps réel, push, clés externes) et déjà signalées par le `DegradedBanner`. **PROUVÉ LIVE (2026-06-07, Playwright + curl)** : 1er build de l'image SPA (la vendorisation de `shared-ui` débloque le build) ; `:3000` redirige vers `…/realms/oria/…auth?client_id=oria-app&…code_challenge_method=S256` ; login `s19test` → app authentifiée, **rechargement sans second login**, **0 erreur console**, `/v1/api/orgs|ventures|sessions` **200** via le front-door nginx (alias `core`) ; token de service valide via `:3000/v1/api/agents` **200** (= core direct) ; **dans le dashboard** `:5100` → onglet Forge → la SPA s'affiche **connectée** dans l'iframe (sélecteur d'org = tenant `s19test`, capture `docs/captures/s19-forge-ok.png`). **2 bugs trouvés & corrigés** : (1) keycloak-js **double-init sous StrictMode** (garde testait `authenticated` encore `undefined` car init PKCE async → 2ᵉ init cassait `login-required`) → garde **niveau module** (`initPromise`) dans `useAuth.jsx` ; (2) **régression d'échappement JS** préexistante exposée par le rebuild du Cœur (`d\'abord` dans une chaîne Python `"""…"""` → apostrophe nue → `SyntaxError` cassant **tout** le script du dashboard, `switchVue` indéfini) → corrigé en `\\'`. **Rugosité honnête** : course au 1er login (la SPA tire `/sessions`+`/ventures` en parallèle → double provisioning → `users_email_unique` 500, **auto-réparé au rechargement** ; défaut de concurrence S17/S18, backlog) ; preuve tenancy A/B *via l'UI* reste à faire sur stack 2 orgs (prolonge le test croisé S18). **Frontière dure tenue** : S19 *affiche* Forge, le **rebranchement métier** des routers reste **S20**. |
| 2026-06-07 | **Sprint S20 v1 livré — 1er router métier de Forge rebranché : `facturation` (priorisé par l'euro)** : le S19 *affichait* Forge ; S20 *rebranche* une **fonction métier** comme outil réel de l'assistant, **un seul router, choisi par valeur commerciale**. **Chantier 0 (décision)** : liste priorisée écrite (`facturation`, `crm`, `stripe`, `contrats`, `ventures`…) sous critère unique *« ça rapproche d'un euro ? »* → **`facturation` retenu n°1** (encaissement direct : devis→facture→paiement) ; `crm` puis `stripe` repoussés au backlog ; pilotage interne (`ventures`/`okr`/`forecast`) gelé. **Chantier 2 (2ᵉ router) délibérément repoussé** (discipline de périmètre). **Étanchéité (bloquant, tranché honnêtement)** : `facturation` scope par **`user.sub`**, pas par `org_id` → **hors** mécanisme `X-Org-ID` audité en S18 ; comme l'adaptateur appelle le core avec **un token de service unique** (`forge-service`), **toutes** les requêtes Workplace tombent sur **une seule identité Forge**. Conséquence : **pas de fuite inter-tenant** (une seule identité traverse l'adaptateur — cohérent avec Workplace **mono-propriétaire**), mais **pas de séparation par utilisateur Workplace** non plus ⇒ **dette explicite** notée : un futur multi-utilisateur réel exigera de **propager le token utilisateur** (pas le token de service) ; ne pas brancher d'autres routers `user_id`-scopés en croyant l'isolation acquise. **Chantier 1 (motif S17 répété)** : `briques/forge/main.py` — capacité `facturation` + 4 routes FR (réutilisant `_appel_protege`/`_json_ou_erreur`) : `GET /facturation` (lister + stats CA encaissé/en attente, filtres `type`/`statut`), `POST /facturation` (créer devis/facture, le core numérote FACT/DEVIS-AAAA-NNNN + calcule HT/TVA/TTC), `POST /facturation/{id}/statut` (`payée`→encaissement), `POST /facturation/{id}/transformer` (devis→facture) ; `core/outils.py` — **lecture libre** `forge_factures_lister`, **actions confirmées** (`confirme=true`) `forge_facture_creer`/`forge_facture_statut`/`forge_facture_transformer`. **PROUVÉ E2E (stack live, 2026-06-07)** : (adaptateur :5700) créer facture **2 950 € HT × 1,20 = 3 540 € TTC** (`FACT-2026-0001`) → marquer **payée** → **CA encaissé 3 540 €** ; devis `DEVIS-2026-0001` → **transformé** `FACT-2026-0002`. (via assistant :5100, **LLM + Gateway**) « liste mes factures + CA » → `forge_factures_lister`, tableau juste ; « crée une facture Garage Leroy 1 200 € HT » → confirmation puis `forge_facture_creer(confirme=true)` → facture réelle (1 440 € TTC) ; **coût Gateway visible** `/assistant/usage` (appels routés comptés ; $0 car modèle local llama-cpp). **Dégradation** core/KC absents → 502/503 clairs (motif S17 inchangé). **Données de test (clients fictifs) supprimées** → facturation re-vidée (CA = 0). **Bilan** : coût d'intégration **faible** (≈1 route + 1 outil/fonction, router core déjà complet) ; **pas encore d'usage métier réel** (à confirmer avant d'en brancher d'autres) ; prochain candidat `crm`, puis `stripe`. |
| 2026-06-07 | **S20 (suite) — 2ᵉ router métier rebranché : `crm` (prospects & pipeline)** : enchaîné sur `facturation` (même sprint, même motif). **Choix** : `crm` en n°2 car il **alimente** la facturation (prospect gagné → devis → facture), bouclant la chaîne commerciale. **Spécificité vs `facturation`** : le CRM scope par **`pole_id` + `user_id`** → lister/créer exige un **pôle** (rattaché à une **venture**). Pour un Workplace **mono-entreprise**, l'adaptateur **masque** ce cérémonial : `_resoudre_pole_crm()` **amorce paresseusement** (une fois) une venture « Workplace » (le core crée 6 pôles dont *Sales*) et mémorise l'id du pôle commercial ; le contrat exposé parle de « prospects », pas de « pôles ». **Bug réel trouvé & corrigé (honnêteté)** : 1ʳᵉ version résolvait via `GET /api/poles` → **liste vide en boucle** (3 ventures parasites) car `list_poles` filtre par `org_id` quand l'utilisateur en a un, alors que les pôles amorcés ont `org_id` **nul** (l'adaptateur n'envoie pas de `X-Org-ID`) → correctif : passer par la **venture** (`GET /api/ventures` scopé `owner_id`, puis `GET /api/ventures/{id}/poles` scopé `venture_id`) → **une seule** venture créée, réutilisée. **Code** : `briques/forge/main.py` — capacité `crm` + 3 routes FR (`GET /crm` lister+pipeline, `POST /crm` créer, `POST /crm/{id}` faire avancer) ; `core/outils.py` — `forge_crm_lister` (lecture), `forge_crm_creer`/`forge_crm_modifier` (actions confirmées). **PROUVÉ E2E (live, 2026-06-07)** : adaptateur :5700 → bootstrap pôle *Sales* → « Claire Fontaine » 8 000 € → **avancée `gagné`** + « Marc Petit » 3 500 € `qualifié` → **pipeline 11 500 €** ventilé ; via assistant :5100 (LLM+Gateway) → « mon CRM + pipeline » → `forge_crm_lister` (tableau juste), « ajoute Sophie Durand 5 000 € » → confirmation puis `forge_crm_creer(confirme=true)` ; **coût Gateway visible** `/assistant/usage` (13 appels, **$0,0024**, repli payant déclenché). **Nettoyage** : prospects + venture/pôles d'amorçage supprimés, adaptateur redémarré (purge cache) → état re-vierge (le bootstrap se recrée au 1er usage). **Même dette d'identité que `facturation`** (token de service unique = une seule identité Forge ; juste en mono-propriétaire). **Bilan S20** : 2 routers (`facturation`+`crm`), chaîne commerciale bouclée ; prochain candidat `stripe`. |
| 2026-06-08 | **Sprint S21 — Stripe réel (encaissement en ligne) : code livré + prouvé OFFLINE** : le `stripe` était un **mock** (`routers/stripe.py`) — session factice + **webhook non vérifié** (n'importe qui pouvait marquer un paiement « payé »). S21 le rend **réel** : (1) **Chantier 1 — SDK + coffre** : `stripe==11.1.0` ajouté à `requirements.txt` ; settings `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`/`STRIPE_SUCCESS_URL`/`STRIPE_CANCEL_URL` (`config.py`) ; **`resolve_stripe_key()`** lit la clé **chiffrée en base** (`ProviderApiKeys` provider `stripe`, déchiffrée via `crypto.py` AES-256-GCM **réutilisé**, pas de nouvelle brique de secret) → repli env, **jamais en clair**, masquée en log ; `stripe` ajouté à la liste providers de `api_keys.py` (chemin coffre réel). **`POST /stripe/checkout`** : clé présente → **vraie** `stripe.checkout.Session.create` (abonnement mensuel, prix inline EUR, success/cancel URLs) → stocke le **vrai** `session.id` ; **sans clé → dégradation honnête `mode:"mock"`** (on ne prétend PAS encaisser). (2) **Chantier 2 — webhook signé (cœur sécurité)** : `POST /stripe/webhook` rendu **public mais à signature vérifiée** (`stripe.Webhook.construct_event` sur corps brut + `Stripe-Signature` + `STRIPE_WEBHOOK_SECRET`) ; signature absente/falsifiée/**corps trafiqué** → **400**, aucun effet ; secret absent → **refuse** (pas de retour au trou du mock). (3) **Chantier 3 — adaptateur + assistant** : `briques/forge/main.py` capacité **`paiement`** + routes FR (`GET /paiement/etat` réel-vs-mock, `/plans`, `/abonnement`, `/paiements`, `POST /paiement/lien`) ; `core/outils.py` — **lecture** `forge_paiement_etat`, **action confirmée** `forge_paiement_lien`. **Décision sécurité** : la **clé ne transite jamais par l'assistant** (configurée hors LLM, au coffre/env). **PROUVÉ OFFLINE (9/9, sans Stripe ni réseau, venv stripe 11.1.0)** : webhook **signature valide → acceptée**, **falsifiée/absente/corps trafiqué → `SignatureVerificationError`** ; coffre **encrypt→decrypt round-trip** OK, clé chiffrée ≠ clair, IV aléatoire (2 chiffrements diffèrent), masquage log ; les 5 fichiers compilent, symboles SDK (`checkout.Session.create`, `Webhook.construct_event`, `StripeError`, `SignatureVerificationError`) tous présents en 11.1.0. **HONNÊTETÉ — non encore prouvé LIVE** : sans clé `sk_test_`, la **création d'une vraie session Checkout contre l'API Stripe** n'a pas été rejouée (le provable hors-ligne — surtout la **vérif de signature**, le vrai risque — l'est à 100 %) ; à rejouer dès qu'une clé de test est fournie. Doc `docs/sprints/S21-forge-stripe-reel.md`. Guide opérationnel `GUIDE-stripe.md` (clés, coffre, `stripe listen`, carte 4242). |
| 2026-06-08 | **Sprint S22 — Emails & relances d'impayés : code livré + prouvé OFFLINE** : prolonge S20/S21 (la facture émise non payée **se relance toute seule** — l'euro **déjà dû**). Socle `app/email.py` (S130, un seul email) **généralisé**. (1) **Chantier 1 — email réel** : `email.py` → `resolve_smtp_password()` (mdp **chiffré** au coffre `ProviderApiKeys` provider `smtp` via `crypto.py` → repli env `SMTP_PASS`, jamais en clair), `send()` générique + templates (**facture émise**, **relance impayée 3 niveaux** J+7 courtois / J+15 ferme / J+30 finale) ; `config.py` ajoute `SMTP_STARTTLS` (relais interne/dev sans TLS) ; provider `smtp` ajouté à `api_keys.py`. (2) **Chantier 2 — moteur relances (cœur valeur)** : `app/relances.py` — `niveau_du()` (cadence pure : <7→aucune, 7–14→J+7, 15–29→J+15, ≥30→J+30), scan des factures `envoyée` échues avec email, **anti-doublon strict** `(facture, niveau)` via **journal SQLite side-car** (motif `proactif.py`, **aucune migration** du schéma Postgres partagé) ; `apercu()` dry-run (n'envoie rien) / `executer()` (envoie+journalise, tolérant aux échecs par facture) ; `routers/relances.py` (`GET /relances/impayes/apercu`, `POST /relances/impayes/executer`, `GET /relances/journal`, `POST /facturation/{id}/envoyer` = email + statut `envoyée` + horloge) monté `/api`. (3) **Chantier 3 — adaptateur + assistant** : capacité `relances` + routes FR ; `forge_relances_apercu` (lecture), `forge_relances_envoyer`/`forge_facture_envoyer` (actions confirmées). **PROUVÉ OFFLINE (15/15, sans identifiants externes)** : **envoi SMTP RÉEL** contre un serveur **aiosmtpd local** (message transmis, destinataire/sujet/numéro/montant vérifiés) ; cadence 6→aucune/8→J+7/20→J+15/40→J+30 ; **aperçu dry-run n'envoie rien**, facture sans email **ignorée signalée**, executer→3 (niveaux 7/15/30), **ré-exécuter→0 (anti-doublon)**, journal=3 ; 8 fichiers compilent. **HONNÊTETÉ — non prouvé LIVE** : envoi vers un **vrai destinataire** (Gmail/transactionnel) + délivrabilité (SPF/DKIM) nécessite des identifiants SMTP ; **planification périodique** = moteur exécutable à la demande, cron quotidien documenté (anti-doublon le rend sûr) pas encore câblé dans la boucle proactive. Doc `docs/sprints/S22-forge-emails-relances.md`, guide `GUIDE-emails.md` (Mailpit dev → SMTP réel, mdp au coffre). |
| 2026-06-08 | **S21+S22 — test d'INTÉGRATION réel (17/17, routers réels + Postgres réel + Mailpit réel)** : au-delà des preuves unitaires offline, les **vrais routers** (`facturation`+`relances`+`stripe`) montés dans une app FastAPI contre un **Postgres dédié** (schéma `init_db`, 87 tables) et **Mailpit** ; seule l'auth Keycloak remplacée (override de dépendance), tout dans un seul event loop (httpx ASGITransport). **Prouvé E2E** : créer facture (TTC 1440 calculé en base) → **envoyer par email** (statut `envoyée`, mail *« Votre facture FACT-2026-0001 »* **reçu dans Mailpit**) → rendre échue J+10 → `apercu` niveau **J+7** + **dry-run silencieux** → `executer` (relance *« Rappel — facture… »* **reçue dans Mailpit**, journalisée) → **ré-exécuter = 0 (anti-doublon)**. Stripe (même run, endpoint réel) : `/stripe/etat`→mock, webhook **sans secret→503 / sig invalide→400 / sig valide→200**. Conteneurs de test supprimés après coup. **Reste live** : chemin Keycloak réel + identifiants SMTP/Stripe externes (cf. guides). |
| 2026-06-08 | **Sprint S23 — Compte client auto à la livraison : code livré + prouvé offline (5/5)**. À la livraison d'une app hébergée, si un **email client** est fourni, on **crée automatiquement son compte d'accès** (Keycloak realm `oria`, **idempotent** par email), Keycloak **lui envoie un lien « définis ton mot de passe »** (`execute-actions-email`, **aucun secret en clair** — option B retenue) et le client est **rattaché à son espace** (`/api/worlds/{id}/rejoindre`, `user_id=sub`). Nouveau module `briques/generateur/client_provisioning.py` (réutilise l'auth de service `workplace-provisioner`), appelé **après** le provisioning de l'espace (besoin du `world_id`) ; statut stocké (`apps.client_onboarding`) et exposé par `GET /apps/{id}`. **Câblage E2E** : `email_client`/`contact_client` traversent `POST /usine/livrer` (+ champs du dashboard) → orchestrateur (`creer_livraison`/`executer_pipeline`/`_etape_generation`, colonnes `livraisons.email_client`/`contact_client`) → `/generer` (`DemandeGeneration`) → onboarding. **Tout best-effort** (jamais bloquant). **Preuve offline** (`test_client_provisioning.py`, Keycloak+Oria mockés `httpx.MockTransport`, 5/5) : nouveau→créé+email+rattaché ; existant→idempotent ; email vide→ignoré (0 appel) ; Keycloak KO→échec sans exception ; SMTP KO→compte créé, email_envoye=False. Migrations SQLite douces. **Reste live** : rôle `realm-management:manage-users` au provisioner + SMTP du realm `oria` (Mailpit) + connexion effective du client. Doc `docs/sprints/S23-forge-compte-client-auto.md`. |
| — | _⬇️ Entrées reconstruites depuis l'historique git (S24 →), plus concises que les sprints rédigés à la main ci-dessus. Le détail vit dans chaque commit + la mémoire projet._ |
| 2026-06-08 | Sprint S24 : pont consenti app livrée → CRM du Forge (prouvé LIVE) (`2dc25ae`) |
| 2026-06-09 | Sprint S25 : persistance backend du thème par user/monde (dettes soldées) (`2cbe150`) |
| 2026-06-09 | Sprint S26 : structure & navigation Oria (état de vue unique + URL + onboarding) (`7085cd1`) |
| 2026-06-09 | Sprint S27 : pont Google Agenda (sync consentie pull one-way, prouvé offline) (`4e5994d`) |
| 2026-06-09 | Sprint S27 : preuve LIVE du pont Google Agenda (`f2928c5`) |
| 2026-06-09 | Sprint S27 : déploiement du pont Google Agenda (image Docker) (`7e5f454`) |
| 2026-06-09 | Sprint S27 : doc — déploiement Docker du pont Google Agenda acté (`52eb398`) |
| 2026-06-10 | Doc : preuve LIVE S138 (chat/cache/routage) + backlog S28-S31 décidé (`7d44890`) |
| 2026-06-10 | Sprint S28 : clôture LIVE groupée — 3 flux Stripe/emails/comptes prouvés (`84dd467`) |
| 2026-06-10 | Sprint S29 : brique horloge (planificateur) — tâches périodiques déclarées par manifest (`a34287c`) |
| 2026-06-10 | Sprint S30 : briefing quotidien — le Jarvis parle le premier (`0f44084`) |
| 2026-06-11 | Sprint S31 : « l'app vivante » — re-audit post-livraison (`561b136`) |
| 2026-06-11 | Sprint S32 : « appliquer l'incrément » + preuve LIVE S31 (`41b78f0`) |
| 2026-06-11 | Sprints S33-S36 : revue autonome, schéma fin, sécu Google, dettes Forge (`f0eab59`) |
| 2026-06-12 | Sprints S37-S38 : multilingue des apps livrées (FR/EN/ES) (`370ae25`) |
| 2026-06-12 | Sprint S39 : Jarvis multilingue (réponses + voix, FR/EN/ES) (`fd6eef5`) |
| 2026-06-12 | Sprint S40 : langue d'interface Oria persistée par compte (User.langue) (`8469afe`) |
| 2026-06-12 | S40 (suite) : i18n du cluster des modales (création/édition/ajout) (`7839719`) |
| 2026-06-12 | S40 (suite) : i18n nav + composants légers (sidebar, notifs, DM, recherche…) (`7c72b19`) |
| 2026-06-12 | S40 (suite) : i18n profil, calendrier, vocal, édition de salle, votes (`d09c81f`) |
| 2026-06-12 | S40 (suite) : i18n abonnements, fil d'activité, agents IA, découverte (`39718fd`) |
| 2026-06-12 | S40 (suite) : i18n membres, conductor, vue monde, réseau (`4dca1d6`) |
| 2026-06-12 | S40 (suite) : i18n apparence, carte du monde, paramètres (`468d6f2`) |
| 2026-06-12 | S40 (suite) : i18n documents (scope) et projets (`8ab7589`) |
| 2026-06-12 | S40 (suite) : i18n gestionnaire de docs + docs intercommunaux (`1971d48`) |
| 2026-06-12 | S40 (suite) : i18n chat agent IA + zones partagées (`f139dd5`) |
| 2026-06-12 | S40 (suite) : i18n config IA (par monde) + Coins membres (`2ac749f`) |
| 2026-06-12 | S40 (suite) : i18n assistant d'onboarding (EasySetupWizard) (`d600849`) |
| 2026-06-12 | S40 (suite) : i18n Jardin Secret (assistant personnel) (`20bd494`) |
| 2026-06-12 | S40 (suite) : i18n méthode IPCRA (Input/Projet/Casquette/Ressource/Archive) (`c6a4692`) |
| 2026-06-12 | S40 (fin) : derniers libellés oubliés (accueil monde, room fermée) (`e13cb22`) |
| 2026-06-12 | S41 (POC) : openWakeWord prouvé sur notre infra → décision GO (`d3846ad`) |
| 2026-06-12 | S42 : brique « ecoute » (wake word openWakeWord) + fournisseur voix dans l'assistant (`179df67`) |
| 2026-06-12 | S43 : paliers commerciaux du wake word (gratuit catalogue + payant commande/Stripe/file horloge) (`65bc004`) |
| 2026-06-14 | S53 : front Studio servi par la brique + iframe dans le Hub Créations Oria (`5b4492e`) |
| 2026-06-14 | Merge pull request #1 from toussaintgarinat-crypto/s53-studio-front-iframe (`630e0e7`) |
| 2026-06-14 | S54 : migration séries Oria → brique studio + décommission atelier_router (`834305f`) |
| 2026-06-14 | S55 : brique vidéo autonome (5970) composée par le Studio + clôture roadmap Studio brique (`07137fa`) |
| 2026-06-14 | S56 : déploiement migration MemPalace → brique mémoire (Forge core/front + Oria) + dette soldée (`96a7222`) |
| 2026-06-15 | Studio dans le noyau : Hub Créations migré d'Oria + l'assistant pilote le Studio (compte clé de service) (`62587ae`) |
| 2026-06-15 | Studio — 2e incrément d'outils assistant : bible fine, distribution/voix, audio (`30cf933`) |
| 2026-06-15 | Oria : retrait de la section Créations (redondante avec le Hub du noyau) (`c23c24a`) |
| 2026-06-15 | S57 : brique transcription souveraine (audio→texte) + archivage notes mémoire/dossier (`3ab070a`) |
| 2026-06-16 | S57+ : transcription branchée à l'assistant + front « capter l'appel » (façon Granola) (`1b953e9`) |
| 2026-06-16 | S57++ : tuile Transcription au dashboard + PWA mobile (capture micro/haut-parleur) (`d0951c0`) |
| 2026-06-16 | S57+++ : capteur d'appel natif macOS (ScreenCaptureKit, façon Granola sans bot/pilote) (`e477a28`) |
| 2026-06-16 | S57++++ : destination Google Drive (OAuth) + diarisation souveraine pyannote activable (`173034a`) |
| 2026-06-16 | S58→S62 : partage de puissance de calcul (« Découplage IA ») (`b0c3643`) |
| 2026-06-16 | Merge pull request #2 from toussaintgarinat-crypto/feat/partage-puissance-calcul-s58-s62 (`50e643a`) |
| 2026-06-17 | feat: export fiche cosmique (personnages v0.3.7) (`0b66a5a`) |
| 2026-06-17 | feat: fiche cosmique — PDF direct + lecture symbolique enrichie (personnages v0.4.0) (`b9a274d`) |
| 2026-06-17 | feat: sauvegarde des personnages (fiches persistées, personnages v0.5.0) (`1ff14d2`) |
| 2026-06-17 | feat: export fiche cosmique en HTML + Markdown (personnages v0.6.0) (`f3eb1d8`) |
| 2026-06-17 | feat: renommer un personnage pour une série (nom de scène) — personnages v0.7.0 (`11b0876`) |
| 2026-06-17 | feat: choisir ses personnages holistiques dans le Studio + nom de scène (studio v0.4.0) (`1910696`) |
| 2026-06-17 | feat: l'assistant crée un personnage holistique en dictant les infos (outil personnage_creer_holistique) (`785d69c`) |
| 2026-06-17 | fix: enregistrement de fiche cassé sur base migrée (INSERT nommé) — personnages v0.7.1 (`010b8ac`) |
| 2026-06-18 | feat: la voix ne coupe plus la parole — fin de tour réglable (mains-libres 5 s par défaut) (`5a23d26`) |
| 2026-06-18 | feat: ranger ses personnages par catégorie libre + l'aléatoire change aussi la ville — personnages v0.8.0 (`8d884cc`) |
| 2026-06-19 | S63+S64 : le système nerveux qui se découvre — capacités appelables (fin du contrat figé) (`0a1e1a3`) |
| 2026-06-19 | S65 : conscience de soi — le Cœur décrit son corps au lieu de l'inventer (`5b76647`) |
| 2026-06-19 | S66 : co-agent exécutif — le « lobe frontal » qui mène un objectif en autonomie (`1efa240`) |
| 2026-06-19 | S67 : pouls autonome — le cœur qui bat tout seul (`e24a335`) |
| 2026-06-19 | S68 : proprioception — le Cœur mesure ses propres sorties (`c6faf4b`) |
| 2026-06-19 | S69 : auto-amélioration des prompts — le Cœur propose, l'humain tranche (`1eac68f`) |
| 2026-06-19 | S70 : Curator + auto-amélioration des capacités — le Cœur révise son corps (façon Hermes) (`5da9f76`) |
| 2026-06-19 | S71 : les yeux — brique vision OCR (cascade souveraine + repli honnête) (`5eb0653`) |
| 2026-06-19 | Brique connexion : pont messageries ↔ assistant (Telegram/WhatsApp/Discord, 5870) (`0c7e951`) |
| 2026-06-19 | Capture : fin de parole (voix) (`8fdd514`) |
| 2026-06-19 | Merge S63→S71 + connexion dans main (organisme vivant + yeux OCR + pont messageries) (`14e6aaa`) |
| 2026-06-19 | Audit infra : modèles Gateway génératifs + tags versionnés + durcissement multi-tenant local (`c07ce58`) |
| 2026-06-19 | Fix : les secrets du .env racine étaient écrasés par les blocs environment des composes (`7efec24`) |
| 2026-06-19 | Telegram quasi temps réel : horloge réactive (tick + cadence poll-telegram) (`e834178`) |
| 2026-06-19 | Conversation speech-to-speech + Gateway MCP (S72→S74) (`4463505`) |
| 2026-06-19 | S73 déploiement : brique voix buildable + Piper souverain réel (`e9303bf`) |
| 2026-06-19 | S73 finition : Piper WAV → Ogg/Opus (bulle vocale Telegram) (`bc23bdf`) |
| 2026-06-19 | S75→S77 : piloter l'amélioration en parlant + boutons d'action + Mini App Telegram (`8f794dd`) |
| 2026-06-19 | S77 fix + S78 + S79 : Mini App auth corrigée, trace unifiée, app complète dans Telegram (`02a121d`) |
| 2026-06-19 | Skill tunnel-miniapp : relancer le tunnel jetable de la Mini App Telegram (`ae06a19`) |
| 2026-06-20 | Agenda « façon TimeTree » : rappels configurables, vue calendrier, ponts TimeTree + Google, étiquettes nommées (`e6af191`) |
| 2026-06-20 | Brique restaurant : commande & paiement à table par QR (multi-tenant) + onglet Atelier unifié (`c7df4e1`) |
| 2026-06-20 | Restaurant v0.2.0 : rendre la brique vendable (sauf paiement réel) (`c22eb49`) |
| 2026-06-20 | Restaurant v0.3.0 : Assistant carte (OCR ancienne carte) + carte pilotable par le Cœur/MCP (`f071827`) |
| 2026-06-20 | fix(restaurant): éviter le piège « env shadow » sur RESTAURANT_KEY/GATEWAY_KEY (`0c729f5`) |
| 2026-06-20 | Restaurant v0.4.0 : générer une carte depuis un concept (en plus de l'import OCR) (`10315c5`) |
| 2026-06-20 | docs(restaurant): captures de la démo Assistant carte (import OCR, génération, carte Vin Cep't) (`86d9800`) |
| 2026-06-20 | fix(restaurant): QR de table injoignable — RESTAURANT_PUBLIC_URL victime du « env shadow » (`32e06b4`) |
| 2026-06-20 | Skill tunnel-restaurant : exposer la brique restaurant (6010) en HTTPS pour QR scannables (`f7c1fa6`) |
| 2026-06-20 | Restaurant v0.5.0 : formats/tailles par plat (bière 25cl/50cl/1L/girafe 2,5L) (`c370a70`) |
| 2026-06-20 | Restaurant v0.6.0 (S80) : stock & rupture automatique temps réel (`82f7f6d`) |
| 2026-06-21 | Restaurant v0.7.0 (S81) : UX client multi-pages + multi-convive correct (`f3b297a`) |
| 2026-06-21 | Restaurant v0.8.0 (S82) : rejoindre la table par code (multi-appareils) (`af08910`) |
| 2026-06-21 | Restaurant v0.9.0 (S83) : répartition flexible de l'addition (`5c43b51`) |
| 2026-06-21 | Restaurant v0.10.0 (S84) : avis clients par QR (`65b65e5`) |
| 2026-06-21 | Paiements v0.1.0 : nouvelle brique « rail d'argent » (Connect, multi-tenant) (`2360bc0`) |
| 2026-06-21 | Restaurant v0.11.0 (S85) : la soirée — surnom, tournée, résumé IA, annulation cuisine (`6409da3`) |
| 2026-06-21 | Mail v0.1.0 : l'assistant lit, trie/filtre par catégorie et résume la boîte de réception (brique 6030, lecture seule) (`e3166d2`) |
| 2026-06-21 | Mail v0.1.1 : plusieurs adresses en une boîte unifiée (filtre par compte + déconnexion) (`c89723b`) |
| 2026-06-21 | Mail v0.2.0 : envoyer une réponse après validation du brouillon (SMTP réel / simulé honnête) (`62e8cff`) |
| 2026-06-21 | Mail v0.2.1 : vrai client mail + onglet « Mail » dans le dashboard (entre Agenda et Profil) (`60029ae`) |
| 2026-06-21 | Registre de briques : afficher le port à côté de la version (et non plus en pied de carte) (`b27fcd7`) |
| 2026-06-21 | Mail v0.3.0 : filtres personnalisés (ex. un par entreprise) + chips Newsletters/Autres (`3feaaf5`) |
| 2026-06-21 | Mail : piloter les filtres (par entreprise) à la voix depuis l'assistant (`7b9ccb8`) |
| 2026-06-21 | Mail : guide intégré « comment connecter mon adresse » (sélecteur de fournisseur) (`69f23b7`) |
| 2026-06-21 | Dev v0.2.0 (S87) : fusion contrôlée + rebuild ciblé (ferme la boucle) (`8c3296c`) |
| 2026-06-21 | Dev v0.3.0 (S88) : flux BMAD léger — le plan d'abord (double gate, DDD) (`4055094`) |
| 2026-06-21 | Dev v0.4.0 (S89) : task trace activable — l'agent raconte ses pas en FR (`eef0e9d`) |
| 2026-06-21 | Cœur S90 : porte à divulgation progressive + prompt caching conditionnel (`0ecf421`) |
| 2026-06-21 | Dev v0.5.0 (S91) : fabrique de skills façon Claude Code + accroche MCP, branchée sur la porte (`7157053`) |
| 2026-06-21 | Dev v0.6.0 (S92) : pilotage du Cœur (dev_demander) + IDE code-server — l'atelier au chat (`dceb33b`) |
| 2026-06-22 | Cœur S93 : Gateway multi-fournisseurs — choix LLM ouvert au dashboard (`ce7d201`) |
| 2026-06-22 | Recherche S94 : brique recherche web souveraine (SearXNG) + lecture de page (`e334116`) |
| 2026-06-22 | Recherche : épingle l'image SearXNG (2026.6.22-952896d29) en dur (`2cb072d`) |
| 2026-06-22 | Dashboard : Gateway hors onglets (→ carte Frontend du registre) + Atelier dev rangé dans les ateliers (`c52fcba`) |
| 2026-06-22 | Dashboard : bulles d'aide en français simple (pour utilisateur non technique) (`260b1e3`) |
| 2026-06-22 | Forge + assistant sur l'abonnement : modèle go/deepseek-v4-flash partout (`7af14da`) |
| 2026-06-22 | Assistant pilote toutes les briques : capacités au manifest (images/video/audit/ecoute/paiements) + dev 5950→5955 (`546fca7`) |
| 2026-06-22 | Mail v0.4.0 : rendu HTML fidèle des emails (iframe sandboxée + DOMPurify + blocage images) (`73e96bb`) |
| 2026-06-22 | Mail v0.5.0 : actions d'écriture (marquer lu / déplacer / supprimer) (`015e1ce`) |
| 2026-06-23 | Launcher : la brique dev (5955) démarre dès le lancement (avant le Cœur) (`32f6a75`) |
| 2026-06-23 | S95 : moteur de bundle dans le generateur (sélection de briques → solution isolée par client) (`69821f0`) |
| 2026-06-23 | S96 : Gateway + assistant (Cœur) dans le bundle (`0e924e0`) |
| 2026-06-23 | S97 : Studio « composeur de solutions » (cocher des briques → bundle par client) (`bfc9c66`) |
| 2026-06-23 | S98 : composeur de solutions exposé au dashboard du Cœur (`ce10627`) |
| 2026-06-23 | S99 : bundle livrable — config Gateway réduite aux modèles démarrables (`c415340`) |
| 2026-06-23 | Intégration Gungnir #1 : brique browser (HuntR) remplace recherche (`98287e4`) |
| 2026-06-23 | Intégration Gungnir #2 : chat vocal temps réel fusionné dans la brique voix (`e3055eb`) |
| 2026-06-23 | Intégration Gungnir #3 : IDE web SpearCode greffé dans la brique dev (`9268253`) |
| 2026-06-23 | Renomme la brique browser → recherche (garde le moteur HuntR) (`75c19e0`) |
| 2026-06-23 | Aligne les tags d'image compose sur les manifests (dev/voix/mail/restaurant) (`6ee8fe6`) |
| 2026-06-23 | Assistant façon Claude/Perplexity : historique dans l'assistant + projets (`ef604d0`) |
| 2026-06-24 | Épopée « Manipulation directe & découvrabilité » (S100→S104) (`4a9528b`) |
| 2026-06-24 | Renomme brique browser→recherche (reliquat Gungnir #1) (`f47462b`) |
| 2026-06-24 | S105 — Brique synopsis v1.0.0 (résumé YouTube IA, port 6090) (`28d7ed0`) |
| 2026-06-24 | Fix synopsis : ajoute GATEWAY_URL au compose (host.docker.internal:4001) (`f2a1288`) |
| 2026-06-24 | Merge integration-gungnir → main (Gungnir #1-#3, S100-S105, manipulation directe, synopsis) (`430c3da`) |
| 2026-06-24 | Ménage racine + reliques : captures→docs/, MemPalace mort, worktree dev (`e44bb07`) |
| 2026-06-24 | Synopsis v1.1.0 — front + résumé de n'importe quelle vidéo + onglet Cœur (`68a1454`) |
| 2026-06-25 | **S106 — Voix de LECTURE haut de gamme (voix v0.6.0)** : Coqui XTTS **activé pour de vrai** (`INSTALL_COQUI=1` au build, `VOIX_COQUI=1` au runtime), **out of the box** (locuteur intégré par défaut `COQUI_SPEAKER_DEFAUT` → aucun WAV requis ; `speaker_wav` reste prioritaire = point d'entrée du clonage S107). **Comparateur de voix de lecture** dans la page de réglage (`GET /`) : le **même** texte de résumé synthétisé par chaque moteur dispo (Coqui / OpenAI / ElevenLabs / Kokoro), côte à côte, ▶︎ puis « 📖 Lecture » en un clic. Licence **CPML** (non commerciale) du modèle XTTS dite honnêtement (UI + README). Voix hébergées documentées au `.env` racine (anti env-shadow). 74 tests verts. **Reste preuve LIVE** (rebuild image + écoute Coqui vs hébergé). |
| 2026-06-28 | **Épopée « refactor clarté & maintenabilité » S114→S125 (CLOSE).** Branche `refactor/s114-routes-coeur`. **S114** Cœur découpé : `core/main.py` **4182 → 71 lignes**, 93 routes extraites par préfixe vers `core/routers/` (systeme/usine/assistant/agenda/profil/dashboard) + `core/etat.py` (registre partagé) + `core/urls_ui.py`. **S115** `core/outils.py` **1642 → 743 l.** : dispatcher éclaté en 8 modules `core/outils_domaines/<dom>.py` + helpers `core/outils_communs.py` (façade conserve `OUTILS` + machinerie capacités). **S116** filet de tests additif : `tests/test_briques_smoke.py` (contrat manifest hors-ligne des 28 briques, zéro collision de port) + `Makefile`/`pytest.ini`/`requirements-dev.txt`. **S117** alignement deps : `constraints-workplace.txt` (source de vérité fastapi/httpx/pydantic/uvicorn…) + `scripts/audit_deps.py` (`make deps-audit`). **S118** naissance de `shared/` : `shared/llm_client.py` (client Gateway unifié) → audit+generateur en wrappers ; pattern **build-context racine** (`COPY shared/` + `conftest.py` + `depend_de_shared` bundle). **S119** contrat Audit→Générateur **figé** : `shared/schemas/audit.py` (Pydantic `Audit`, `response_model`). **S120** JWT Keycloak unifié : `shared/workplace_auth.py` (RS256/JWKS), migration donnees+agenda+forge brique par brique ; oria gardé sur sa vendored (sous-stack découplé) ; restaurant (HMAC) + memoire (HS256) hors périmètre. **S121** prépa multi-tenant : `core/contexte_tenant.py` (X-Org-ID/X-User-Id/X-Forge-User-Token), donnees scopé par org (migration idempotente). **S122** voix branchée au Cœur (5 capacités déclaratives). **S123** design system partagé `shared/static/workplace.css` (tokens `--wp-*`) + fronts uniformisés. **S125** runbook bascule HP (`MIGRATION-HP.md` + `scripts/preflight_hp.sh`). **S124** (ce sprint) nettoyage & doc : 3 guides ajoutés (ci-dessous), restaurant documenté **autonome** (gardé dans le repo, choix utilisateur), épopée close. Pattern shared/ triplement prouvé (S118/S119/S120). Reste les **preuves LIVE Docker groupées** sur le HP (régime preuve différé). |
| 2026-06-28 | **3 guides « comment faire » ajoutés à la racine** : `GUIDE-ajouter-une-brique.md`, `GUIDE-ajouter-un-outil.md`, `GUIDE-modifier-l-auth.md`. Point d'entrée pour étendre Workplace sans relire tout le code. |
| 2026-07-02 | **S133 — L'assistant pilote TOUTES les briques** : +22 capacités dans 7 manifests (ETL +3, Transcription +1, Personnages +5, Studio +4, Données +3, Générateur +4, Connexion +2) → ~130 outils LLM actifs. Zéro modification du Cœur. |
| 2026-07-02 | **S134 — Migration outils statiques → manifests** : Forge (14 outils), Mémoire (2), Studio (12), Personnages (2) sortis de `outils.py` et déclarés dans leurs manifests. `socle:true` câblé pour inclusion systématique. 39 tests verts. |
| 2026-07-03 | **S139 — CORS hardening** : `CORS_ORIGINS=*` commenté dans `.env.example` (valeur par défaut sécurisée `localhost:5100,3003`). `donnees` reçoit `env_file: ../../.env` (manquant). Les 8 briques avec `env_file` injectent CORS depuis le `.env` racine (sans écraser via `environment:`). `.env` HP : origines réelles `192.168.1.89:5100,3003`. **PROUVÉ LIVE (HP)** : origine inconnue → ACAO absent (400) ; origine légitime → `Access-Control-Allow-Origin: http://192.168.1.89:5100` ✅. |
| 2026-07-03 | **S140 — Secrets PeerTube** : `.env` peertube contient des secrets forts (non commité, protégé par `.gitignore`), `.env.example` avec placeholders clairs, `postgres:16.14-alpine` épinglé, `PEERTUBE_HOST` paramétré. Brique sécurisée, prête pour le HP. |
| 2026-07-03 | **S141 — Mot de passe DB Forge** : `FORGE_DB_PASSWORD` fort généré (`openssl rand -hex 24`) et ajouté dans `.env` racine. `.env.example` ligne 78 décommentée avec placeholder `GENERER_openssl_rand_-hex_24`. Le docker-compose Forge lit déjà la variable — le placeholder `forge_secret_change_this` n'est plus utilisé. ⚠️ Si le volume `forge-db` existe avec l'ancien mot de passe, recréer le volume au prochain démarrage. |

---

## 8. Questions ouvertes (à trancher plus tard)

- Le **Cœur** : écrit en **Python / FastAPI** ✅ (cohérent avec MemPalace/Forge/Assistant).
- Le **registre de briques** : format manifest acté (JSON, clés : `nom`, `version`, `description`, `role`, `statut`, `chemin_source`, `port`, `url_sante`, `depends_on`, `offre`, `besoin`). ✅
- ~~**Authentification** unifiée (Keycloak est déjà présent dans Forge/Oria) → à harmoniser.~~
  ✅ **Résolu S120** : Keycloak RS256/JWKS unifié dans `shared/workplace_auth.py` (donnees/agenda/forge
  migrées ; oria sur sa vendored, sous-stack découplé). NB : restaurant (HMAC) et memoire (HS256) sont
  des schémas distincts **volontairement séparés**. Voir `GUIDE-modifier-l-auth.md`.
- Déploiement : tout en Docker Compose local d'abord, cloud ensuite.
- ~~**Contrat Audit → Générateur à figer** (dette repérée le 2026-06-03).~~ ✅ **Résolu S119** : schéma
  partagé `shared/schemas/audit.py` (Pydantic `Audit`, `extra="allow"`) — `audit` le pose en
  `response_model` sur `GET /audits/{id}`, `generateur` le valide à la consommation (`Audit.model_validate`).
  Prouvé LIVE 2026-06-28 (le conteneur generateur valide la sortie réelle du producteur).
- **LLM de prod** : décider du modèle par défaut des briques. Local (Ollama) impossible sans GPU sur cette
  machine ; OpenRouter gratuit instable. Piste : `gpt-4o-mini`/`gemini-flash` (cheap) en défaut, gratuit en option.
