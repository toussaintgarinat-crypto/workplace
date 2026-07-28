# S210 → S215 — Ingestion, connecteurs et dette du tour du 2026-07-28

Six sprints issus du tour de la brique `app-builder` et de la comparaison de la brique `etl`
avec Airbyte (2026-07-28).

**Le constat qui a réorienté ce backlog.** Partir d'Airbyte a fait remonter un défaut sans
rapport avec l'ETL, et bien plus grave : le **contrat entre un manifeste et sa route n'est
vérifié nulle part**. `tests/test_briques_smoke.py:85` valide seulement que chaque capacité
porte un `nom` ; personne ne compare les `params` déclarés à la signature réelle de
l'endpoint. Résultat : au moins une capacité est **morte depuis son écriture**, et quatre
autres mentent à l'assistant. C'est S210, et c'est le sprint le plus rentable du lot.

**Ordre = risque décroissant, pas effort croissant.** S210 corrige des capacités cassées.
S211 ferme un trou de sécurité. S212 est de la robustesse. S213 solde une ambiguïté du repo.
S214 est le seul sprint de valeur neuve. S215 est du confort, sautable.

Chaque sprint est indépendant, sauf mention explicite. Le plan d'implémentation détaillé
(`docs/superpowers/plans/`) s'écrit **au moment d'attaquer**, pas d'avance — motif du repo.

---

## S210 — Le contrat manifeste ↔ route n'est vérifié nulle part

**Pourquoi maintenant.** Ce n'est pas une hypothèse, c'est mesuré. Un scan des 36 briques
portant du code compare les `params` déclarés dans `capacites` au code de la brique. Cinq
paramètres déclarés n'existent nulle part, sur quatre briques — et le pire est le premier :

| Brique | Capacité | Déclaré au manifeste | Attendu par le code | Effet réel |
|---|---|---|---|---|
| `connexion` | `connexion_envoyer` | `destinataire`, `message` | `id_externe`, `texte` (`main.py:57`) | **422 systématique — capacité morte** |
| `transcription` | `transcription_fichier` | `url_fichier` | `UploadFile` multipart (`main.py:187`) | pas de transcription par URL, l'endpoint ne sait pas faire |
| `personnages` | `personnage_fiche_modifier` | `nom_scene` | `body.nom` (`main.py:339`) | renommage ignoré |
| `personnages` | `personnage_distribution_proposer` | `fiches_ids` | modèle `Proposer` (`main.py:191`) | param fantôme |
| `generateur` | `generateur_app_generer` | `nom_client` | `DemandeGeneration` (`main.py:222`) | param fantôme, ignoré en silence |

`connexion_envoyer` est le cas dur : deux params sur trois sont faux, donc Pydantic rejette le
corps et l'assistant se prend un 422 **à chaque tentative d'envoi de message**. La capacité
n'a jamais pu fonctionner.

À ça s'ajoute le cas `etl`, que le scan **rate** (les mots `dossier` et `statut` existent
ailleurs dans le fichier) : `etl_documents_lister` déclare les filtres `dossier` et `statut`,
l'endpoint `GET /documents` (`briques/etl/main.py:129`) accepte `categorie`, `projet`,
`entreprise_id`, `limite`, `offset`. FastAPI ignore les query params inconnus **sans erreur** →
l'assistant croit filtrer et reçoit la liste entière. Le pire genre de bug : muet.

Ce dernier cas dit aussi que **le scan par grep ne suffit pas** comme critère de sortie : il
sur-signale (un mot présent ailleurs) et sous-signale. Le test doit lire la vraie signature.

**Périmètre.**
- Écrire dans `tests/` un test paramétré sur les 39 manifestes qui, pour chaque capacité,
  **introspecte la route** (signature FastAPI + modèle Pydantic du corps) et vérifie que
  chaque `param` déclaré existe, et que chaque champ **requis** du modèle est déclaré. Import
  du module de la brique, pas d'expression régulière.
- Décider du sens de la correction, capacité par capacité — c'est un arbitrage, pas de la
  mécanique : ou bien le manifeste s'aligne sur le code, ou bien le code prend le nom du
  manifeste (souvent le meilleur, `destinataire` est plus parlant que `id_externe` pour un
  LLM). Le renommage d'un champ de modèle a un rayon d'action : vérifier les appelants.
- Corriger les 5 + 1 cas ci-dessus.
- Traiter les briques hors-Python (`agenda` route ses handlers hors `main.py`) : soit le test
  sait les introspecter, soit elles sont explicitement exemptées **avec un motif écrit**, pas
  par omission.

**Critère de sortie.** `connexion_envoyer` envoie réellement un message, prouvé par un test.
Le test de contrat passe sur toutes les briques non exemptées, et **échoue** si on réintroduit
à la main un des 6 écarts.

**Effort.** ~1 jour. **Dépend de.** Rien.

---

## S211 — ETL : la brique est ouverte et sert de proxy vers le réseau interne

**Pourquoi maintenant.** Deux trous qui se combinent mal.

`briques/etl/main.py` ne contient **aucune** occurrence de `API_KEY`, `CORS` ou `Depends` :
la brique est sans authentification sur le port 5200, alors que le sprint « CORS + API_KEYS
briques autonomes » avait durci 8 briques. `etl` est passée à travers.

Et `extraction.extraire_depuis_url` (`extraction.py:134`) fait un `httpx.get` avec
`follow_redirects=True` sur **n'importe quelle URL**, sans liste blanche ni blocage des
adresses privées. La validation `HttpUrl` de Pydantic laisse passer `http://gateway:5100` ou
`http://192.168.1.89`. Combiné à l'absence d'auth : quiconque atteint 5200 s'en sert comme
proxy d'exploration du réseau Docker, et **récupère le corps de la réponse** dans le document
ingéré. C'est une SSRF exploitable, pas théorique.

Troisième point, mineur mais du même endroit : l'upload est plafonné à 50 Mo
(`main.py:67`), **pas** l'ingestion par URL. Une réponse énorme part directement en mémoire.

**Périmètre.**
- Clé API + CORS sur `etl`, motif exact des 8 briques déjà durcies (ne pas réinventer :
  reprendre `cle_api` de `briques/connexion/main.py` ou `briques/transcription/main.py`).
  Attention aux appelants : la brique `audit` déclare `besoin: ingestion_fichier` — elle devra
  porter la clé.
- Garde SSRF sur `/ingerer/url` : résolution DNS puis refus des plages privées/loopback/
  link-local, **et re-vérification après chaque redirection** (une redirection vers 127.0.0.1
  est le contournement classique).
- Plafond de taille sur l'ingestion URL, aligné sur les 50 Mo de l'upload, en streaming
  (`httpx.stream`) pour ne pas charger avant de mesurer.

**Critère de sortie.** Un test qui prouve qu'une URL pointant sur une IP privée est refusée
**y compris via redirection**, un test qui prouve qu'un appel sans clé est rejeté, un test de
plafond. La brique `audit` continue d'ingérer, prouvé bout-en-bout.

**Effort.** ~1 jour. **Dépend de.** Rien. *(À faire avant toute exposition de `etl` sur le mesh.)*

---

## S212 — ETL : l'OCR gèle la brique entière

**Pourquoi maintenant.** `ingerer_fichier` est `async def` (`main.py:62`) et appelle
directement `extraction.extraire_texte`, qui est du CPU **synchrone** : PyMuPDF, puis
Tesseract à 200 dpi page par page (`extraction.py:56-62`). Ça s'exécute dans la boucle
d'événements → pendant l'OCR d'un PDF scanné, la brique ne répond plus à rien, `/sante`
compris. Le healthcheck du `docker-compose.yml` (timeout 10 s, 3 essais) déclare donc la
brique **unhealthy** sur un simple gros document, et Docker la marque en échec alors qu'elle
travaille. Même motif que le « 500 fantôme du digest » : le travail aboutit, la plateforme dit
qu'il a échoué.

Deux fragilités du même fichier tant qu'on y est :
- `markitdown==0.0.1a3` est une **alpha**, et c'est le chemin d'extraction **principal**
  (`extraction.py:111`) : tout y passe avant les fallbacks. Une alpha épinglée en position
  critique, sans test qui verrouille son comportement.
- L'API expose `PATCH /documents/{id}/classement` et `GET /dossiers`, mais **aucune capacité**
  ne les déclare : tout le rangement (catégorie, projet, entreprise, tags) est inaccessible en
  conversation, alors que le code le supporte depuis S6.

**Périmètre.**
- Passer l'extraction en `run_in_threadpool` (ou executor dédié) sur les deux chemins
  d'ingestion. Vérifier que le healthcheck reste vert pendant un OCR long — c'est le vrai test.
- Statuer sur `markitdown` : bumper vers une version stable si elle existe, sinon **écrire les
  tests de non-régression d'extraction** (un PDF, un DOCX, un XLSX de référence) avant de
  toucher quoi que ce soit. Ne pas bumper à l'aveugle un composant sans filet.
- Ajouter les capacités `etl_classer_document` et `etl_dossiers_lister` au manifeste — en
  respectant le contrat vérifié par S210.

**Critère de sortie.** Un OCR de plusieurs minutes ne fait pas tomber `/sante`. L'assistant
sait ranger un document dans un projet en conversation, prouvé.

**Effort.** ~1 jour. **Dépend de.** S210 pour la forme des nouvelles capacités (sinon on
réintroduit le défaut qu'on vient de corriger).

---

## S213 — app-builder : trancher entre la servir et la sortir

**Pourquoi maintenant.** État vérifié le 2026-07-28 : `briques/app-builder/` contient un
manifeste et **un seul fichier HTML de 677 Ko / 11 849 lignes**. Zéro service dans les
`docker-compose*.yml`, zéro route Caddy, zéro lien depuis le dashboard, zéro test. Ouverte
dans un navigateur, **elle fonctionne** : aucune erreur JS, 14 onglets, projet de démo,
questionnaire 4 phases, exports Markdown/JSON/Docker Compose/Terraform. C'est un outil riche
et vivant que **personne ne peut atteindre** sans ouvrir le fichier à la main.

C'est une ambiguïté coûteuse : elle compte comme brique dans `core/conscience.py:35` et dans
les tests, mais n'existe pas à l'exécution. Il faut trancher, pas laisser pourrir.

Trois défauts constatés à l'ouverture, quel que soit le choix :
- `<link rel="manifest" href="manifest.json">` pointe sur le **manifeste de brique
  Workplace**, pas sur un manifeste PWA → l'installation PWA ne peut pas marcher.
- Version incohérente sur trois supports : titre `V3.0`, `manifest.json` `2.8.0`, nom de
  fichier `v2`.
- React + Babel standalone chargés depuis **unpkg.com** : dépendance Internet à l'ouverture,
  et Babel transpile 677 Ko de JSX **dans le navigateur** à chaque chargement — il émet
  lui-même l'avertissement `code generator deoptimised, exceeds max of 500KB`.

**Périmètre.** Écrire l'ADR (`docs/decisions/`) qui tranche entre :
- **(a) La servir** : conteneur statique (nginx/Caddy), entrée dashboard, route mesh, entrée
  au filet `scripts/tests_briques.sh`. Corriger au passage le manifeste PWA, aligner les
  versions, et **vendorer React/Babel** pour couper la dépendance CDN — ou mieux, précompiler
  le JSX et supprimer Babel du navigateur.
- **(b) La sortir du repo** vers son propre dépôt, comme le Calendrier Familial, et retirer
  proprement les références (`conscience.py`, `catalogue.py`, tests, `bundle.py:42`).

Point de décision qui pèse sur l'ADR : l'outil appelle **en direct depuis le navigateur**
`api.anthropic.com`, `api.openai.com`, `api.mistral.ai`, Cohere, Perplexity, OpenRouter,
Ollama, DeepSeek, Gemini, LM Studio — avec des clés saisies par l'utilisateur et stockées en
`localStorage`. **Aucune référence à la Gateway `:5100`.** Donc : pas de budget LLM, pas de
cache sémantique, pas de journal des coûts, et des clés en clair dans le navigateur. Le
choix (a) rend ce défaut public et impose de le corriger ; le choix (b) l'assume comme outil
personnel hors stack. C'est la vraie question de l'ADR, pas l'hébergement.

**Critère de sortie.** Plus aucune ambiguïté : soit la brique est atteignable et au filet de
test, soit elle n'est plus dans `briques/`. Pas de troisième état.

**Effort.** ~0,5 j pour (b), ~2 j pour (a) — dont le branchement Gateway.
**Dépend de.** Rien.

---

## S214 — Brique `connecteurs` : les connecteurs Airbyte sans la plateforme Airbyte

**Pourquoi maintenant.** Le manque réel que révèle la comparaison avec Airbyte est précis :
**Workplace sait ingérer du document, mais ne sait pas aller chercher de la donnée structurée
chez un tiers, de façon planifiée et reprenable.** Aujourd'hui chaque brique bricole son
propre fetch — `veille-info` fait du RSS, `gateway-sync` appelle OpenRouter — sans état
partagé, sans reprise, sans mutualisation. Le prochain connecteur sera encore réécrit à la main.

**Ce qu'on ne fait pas, et pourquoi.** On **ne déploie pas la plateforme Airbyte**. `abctl`
monte un cluster Kubernetes (kind) avec server, webapp, worker, Temporal, cron, bootloader,
Postgres et MinIO — 8 Go de RAM recommandés. Le HP est un 800 G4 i7-8700 qui fait déjà tourner
~54 conteneurs ; techniquement ça tiendrait sur 6 cœurs, mais ce serait une pile Java +
Kubernetes + Temporal greffée sur un stack uniformément FastAPI + docker compose + manifestes.
Corps étranger, charge d'exploitation disproportionnée pour un opérateur unique. Second motif,
qui pèse vu l'épopée « bundles solutions par client » : la plateforme est en double licence
**MIT/ELv2**, et l'ELv2 interdit de l'offrir comme service managé à des tiers.

**Ce qu'on fait à la place.** **PyAirbyte** (`pip install airbyte`, **MIT**, v0.29+) : la même
bibliothèque de 600+ connecteurs, utilisable comme simple librairie Python, sans plateforme,
sans Temporal, sans Kubernetes. Elle gère la synchro incrémentale et l'état. Point décisif
pour nous : les connecteurs **déclaratifs YAML** et les connecteurs **Python** s'installent en
venv — **sans accès au socket Docker**, qui est le bloquant connu du sprint Sablier. Et les
manifestes YAML low-code collent à la philosophie de manifestes du repo.

**Périmètre.**
- Brique FastAPI `connecteurs`, port libre, motif standard : `manifest.json` avec `capacites`,
  clé API, CORS, healthcheck, `Dockerfile`, entrée au filet `scripts/tests_briques.sh`.
- Une source = une configuration persistée ; état/curseur en SQLite pour l'incrémental.
- Planification via l'**horloge** : tâche déclarée dans le manifeste, motif exact de
  `veille-info` (`main.py:60`, jeton horloge inclus) — ne pas inventer un ordonnanceur.
- **Périmètre volontairement réduit au premier tour** : deux ou trois connecteurs réellement
  utiles (Stripe, GitHub, Google Sheets sont les candidats crédibles vu les briques
  existantes), pas les 600. Le but est de prouver le motif — installation, sync, état, reprise
  après échec — pas de couvrir le catalogue.
- Trancher explicitement, dans l'ADR, **où atterrissent les données**. La brique `donnees`
  (5500) est un CRUD multi-tenant, pas un entrepôt analytique. Réponse par défaut de ce
  sprint : les données restent dans le cache local de la brique, et on ne construit **pas**
  d'entrepôt. Voir le non-sprint ci-dessous.

**Critère de sortie.** Une source tierce synchronisée deux fois de suite ne retransfère que le
delta (état vérifié), et une sync interrompue reprend où elle en était. Prouvé par test, puis
LIVE sur le HP.

**Effort.** ~3-4 jours. **Dépend de.** Rien, mais à faire **après** S210 (le motif de capacité
doit être sain avant d'en écrire de nouvelles).

**Non-sprint assumé — brique `entrepot` (DuckDB).** C'est le prolongement logique de S214 et
la destination naturelle des données synchronisées. On ne le fait **pas** maintenant : tant que
rien ne produit de donnée structurée en volume, c'est du YAGNI — même verdict que S192. À
rouvrir seulement si `connecteurs` tourne et déborde.

---

## S215 — Renommer `etl` en `ingestion` — confort, sautable

**Pourquoi maintenant, et pas avant.** La brique `etl` **n'est pas un ETL**. Elle extrait du
texte de documents non structurés (PDF, Word, images, HTML) vers SQLite, pour la brique
`audit`. Elle ne réplique aucune table, ne suit aucun curseur, ne planifie rien. Sa `famille`
au manifeste dit d'ailleurs déjà `ingestion` — c'est le `nom` qui ment.

Ce renommage ne vaut pas son coût aujourd'hui : c'est du churn sur `core/conscience.py:35`,
`core/catalogue.py`, `briques/generateur/bundle.py`, les tests, le `besoin` de la brique
`audit`, le volume Docker et le chemin de la base. **Il devient rentable au moment où S214
livre `connecteurs`** : à ce moment-là on a deux briques côte à côte, une nommée `etl` qui ne
fait pas d'ETL et une nommée `connecteurs` qui en fait — et la confusion coûte plus cher que
le renommage.

**Périmètre.** Renommage `etl` → `ingestion` : dossier, `nom` du manifeste, références au
Cœur, filet de test. **Migration du volume Docker et du chemin `/data/etl.db`** — c'est le
seul point à risque, tout le reste est mécanique. Prévoir la reprise des documents déjà
ingérés, ou décider explicitement de repartir à vide.

**Critère de sortie.** Aucune référence à `etl` hors historique Git. Les documents déjà
ingérés sont toujours lisibles après migration (ou leur perte est un choix écrit).

**Effort.** ~0,5 j. **Dépend de.** S214 — sans lui, ce sprint ne vaut pas son coût.

---

## Récapitulatif

| Sprint | Objet | Risque traité | Effort | Dépend de |
|---|---|---|---|---|
| **S210** | Contrat manifeste ↔ route | capacité morte + 5 dérives silencieuses | ~1 j | — |
| **S211** | ETL : auth + SSRF + plafond | trou de sécurité exploitable | ~1 j | — |
| **S212** | ETL : OCR non bloquant, markitdown, classement | indisponibilité + alpha en position critique | ~1 j | S210 |
| **S213** | app-builder : servir ou sortir | ambiguïté du repo + clés en `localStorage` | 0,5-2 j | — |
| **S214** | Brique `connecteurs` (PyAirbyte) | *valeur neuve* | ~3-4 j | après S210 |
| **S215** | Renommer `etl` → `ingestion` | confort | ~0,5 j | S214 |

Total ~7 à 9 jours. S210 et S211 sont les deux seuls que je ferais **sans attendre** :
l'un répare des capacités qui ne marchent pas, l'autre ferme une porte ouverte.
