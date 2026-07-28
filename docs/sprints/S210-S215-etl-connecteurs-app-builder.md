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

> **✅ FAIT le 2026-07-28.** Filet : `tests/test_contrat_capacites.py` (242 capacités, 3 règles).
> Décisions consignées dans `docs/decisions/2026-07-28-contrat-manifeste-route.md`.
> **11 écarts trouvés, pas 6** — le scan préparatoire en ratait la moitié :
>
> | Brique | Capacité | Écart réel | Correction |
> |---|---|---|---|
> | `connexion` | `connexion_envoyer` | 422 — **morte** | manifeste → `id_externe`/`texte` |
> | `donnees` | `donnees_modifier` | 404 — **morte**, segment `/enregistrements` absent du `chemin` | chemin corrigé |
> | `donnees` | `donnees_supprimer` | 404 — **morte**, même cause | chemin corrigé |
> | `transcription` | `transcription_fichier` | multipart, **inappelable** par l'assistant | capacité retirée |
> | `transcription` | `transcription_depuis_url` | `resume` fantôme | param retiré, `transcription_resumer` ajoutée (`POST /resumer`, jamais déclarée) |
> | `etl` | `etl_documents_lister` | `dossier`/`statut` fantômes | vrais filtres déclarés |
> | `etl` | `etl_ingerer_url` | `dossier` fantôme | param retiré |
> | `generateur` | `generateur_app_generer` | `nom_client` fantôme | → `contact_client` + `email_client` |
> | `personnages` | `personnage_fiche_modifier` | `nom` requis non déclaré ; `categorie` vit sur une autre route | réduite au renommage |
> | `personnages` | `personnage_portrait_generer` | `fid`/`style` fantômes **et description fausse** (aucune image produite) | params réels + description honnête |
> | `personnages` | `personnage_distribution_proposer` | `contexte`/`fiches_ids` fantômes | → `premisse`/`combien`/`langue`/`deja` |
>
> Ce que le backlog n'avait pas vu : les deux capacités mortes de `donnees` (l'écart est dans
> le **chemin**, pas dans les params), et le fait que `agenda` s'introspecte très bien (ses 17
> capacités sont couvertes) — **aucune exemption** n'a été nécessaire. Zone laissée non
> vérifiée, et assumée : les corps `dict` libres des proxys `forge` (skip explicite).
> Preuve d'appel réel : `briques/connexion/test_main.py::test_connexion_envoyer_delivre_avec_les_params_du_manifeste`.

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

> **✅ FAIT le 2026-07-28.** Garde SSRF dans `briques/etl/reseau.py`, auth+CORS dans
> `briques/etl/main.py`, clé portée par les 5 chemins câblés du Cœur et par la brique `audit`.
> Preuves : `briques/etl/test_securite.py` (17 tests) et `core/test_etl_cle_service.py`
> (8 tests) — `make test-core` 521 ✓, `make smoke` 994 ✓, brique `audit` 11 ✓.
>
> Trois choses que le périmètre écrit d'avance ne disait pas :
>
> - **La clé seule ne ferme rien, et la fermer par `API_KEYS` aurait cassé la flotte.**
>   `_entetes_brique` envoie `{BRIQUE}_KEY` en `X-API-Key`, mais c'est la liste **côté
>   brique** qui décide de refuser — il faut donc deux variables. Le réflexe (réutiliser la
>   variable générique `API_KEYS`, motif des 8 briques durcies) s'est révélé **faux ici** :
>   sur le HP, `API_KEYS` n'est posée nulle part et **22 briques la lisent via `env_file`**
>   depuis le `.env` racine. La poser pour fermer l'ETL les aurait toutes basculées en
>   fail-closed d'un coup, alors que leurs appelants présentent une clé dédiée
>   (`{BRIQUE}_KEY`) qui n'y figure pas → 401 partout. D'où **`ETL_API_KEYS`**, dédiée, qui
>   prime sur la générique sans s'unir à elle (une union rouvrirait l'ETL à quiconque
>   détient n'importe quelle clé de la flotte). `API_KEYS` reste un repli pour un
>   déploiement fermé de bout en bout.
> - **Cinq chemins câblés ignoraient `_entetes_brique`**, pas un : usine (`_etape_ingestion`),
>   cycle de vie (décrocher/reprendre), tick proactif « documents à classer », dépôt de
>   document du front, outils du domaine `documents`. Les capacités du manifeste, elles,
>   passaient déjà par le helper. La résolution `{BRIQUE}_KEY` est remontée dans
>   `orchestrateur.entetes_brique` — `outils_communs` importe `orchestrateur`, l'inverse est
>   impossible, et les chemins câblés n'avaient donc aucun helper accessible. D'où un test
>   **par chemin**, pas un test sur le helper.
> - **`/sante` reste ouverte** : le healthcheck du compose n'a pas de clé à présenter.
>   La fermer aurait rendu la brique `unhealthy` dès la première clé posée.
>
> **Limite assumée, pas corrigée** : entre notre résolution DNS et celle de httpx, un
> résolveur hostile peut changer sa réponse (DNS rebinding). Fermer ce trou impose de se
> connecter à l'IP vérifiée avec un `Host` forcé — infaisable en HTTPS sans casser la
> vérification du certificat. Le cas réaliste (URL interne, redirection vers la loopback)
> est couvert et testé ; le rebinding actif ne l'est pas. C'est documenté dans le docstring
> de `reseau.py`.
>
> **✅ LIVE sur le HP le 2026-07-28** (`4fe3749`) — `ETL_KEY` + `ETL_API_KEYS` posées dans
> le `.env` racine, `etl` / `audit` / `core` rebuildés, stack entier healthy.
>
> La faille a été prouvée **avant** correction, pas seulement décrite : un `POST
> /ingerer/url` **sans aucune clé** sur `http://192.168.1.89:5100/dashboard` a fait
> récupérer et stocker la page de login Keycloak, relisible via `/documents/{id}`.
>
> | Preuve LIVE | Avant | Après |
> |---|---|---|
> | `GET /documents` sans clé | 200 | **401** |
> | `GET /documents` mauvaise clé | 200 | **401** |
> | `GET /documents` bonne clé | 200 | 200 |
> | `GET /sante` sans clé (healthcheck) | 200 | 200 |
> | `POST /ingerer/url` → `192.168.1.89` | 200 + corps stocké | **403** |
> | `POST /ingerer/url` → `example.com` | 200 | 200 |
> | `audit._recuperer_tous_ids()` | 27 docs | 27 docs |
> | `GET /assistant/dossiers` (Cœur) | 200 | 200 |
>
> La générique `API_KEYS` est restée **absente** du `.env` racine : les 22 autres briques
> qui la lisent n'ont pas bougé. Documents créés par ces tests supprimés après coup.
>
> **Défaut trouvé APRÈS coup, sur le stack en marche** (`a1ccb7d`) : le `CORS_ORIGINS=${CORS_ORIGINS:-*}`
> que j'avais ajouté dans `environment:` reproduisait le piège env-shadow — il s'interpole
> depuis le dossier du compose, pas depuis l'`env_file`, et mettait donc la brique en CORS
> `*` alors que le `.env` racine déclare une liste restreinte. Corrigé en supprimant le bloc
> `environment:` (le code a déjà les bons défauts) ; vérifié dans le conteneur.
> Le même défaut était **préexistant sur 13 autres briques** — pas seulement `veille-info` et
> `mail` : oria, dev, restaurant, paiements, veille-prospection, atelier-images-video,
> telephonie, recherche, atelier-veille, synopsis, voix, geo. Balayé dans la foulée
> (`ceb24de`), les 14 recréées sur le HP, toutes 200 sur leur port de manifeste. Restreindre
> le CORS ne casse aucun front : ils appellent tous en chemin relatif (`API_BASE` vide en
> autoporté, ou préfixe `/atelier-veille-app` quand le Cœur les sert) → même origine.
> `peertube` et `calcul.pi` gardent leur ligne : ils n'héritent pas du `.env` racine.

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

> **✅ FAIT le 2026-07-28.** Pool d'extraction dédié dans `briques/etl/extraction.py`,
> filet d'extraction (`test_extraction.py`), preuve du non-blocage (`test_ocr_non_bloquant.py`),
> round-trip du rangement (`test_classement.py` + `core/test_classement_documents.py`).
> Brique **51 ✓**, `make test-core` **527 ✓**, `make smoke` **994 ✓**.
>
> **Le troisième point du périmètre reposait sur une prémisse fausse, et n'a pas été fait.**
> « Aucune capacité ne déclare `PATCH /classement` ni `GET /dossiers` » est exact ; la
> conclusion « tout le rangement est inaccessible en conversation » ne l'est pas. Les deux
> gestes sont **câblés en dur depuis S6** — `classer_document` et `lister_dossiers` dans
> `core/outils.py`, dispatch dans `core/outils_domaines/documents.py`, gate de confirmation
> compris. Les ajouter au manifeste aurait donné à l'assistant **deux outils jumeaux** pour
> le même geste, soit exactement le brouillage que S210 vient de nettoyer. Ce qui manquait
> vraiment, ce n'était pas la capacité mais la **preuve** : rien ne vérifiait qu'un document
> classé se retrouve dans son dossier, ni que le corps envoyé par le Cœur soit le bon. C'est
> ce qui a été écrit à la place (9 tests). Une migration hardcodé → manifeste reste possible,
> mais c'est un autre sujet que celui de ce sprint.
>
> **Le filet d'extraction a trouvé deux corruptions muettes**, écrites avant le bump comme le
> périmètre l'exigeait — et c'est lui qui a payé, pas le bump :
>
> | Défaut | Effet mesuré | Correction |
> |---|---|---|
> | markitdown recevait le **texte brut** et faisait deviner l'encodage : un octet nul → « UTF-16 » | `a\x00b\x07Griffon-Sextant-42` stocké en `愀戇䝲楦景渭卥硴慮琭㐲`, sans erreur | court-circuit du texte brut avant markitdown |
> | PDF de moins de 100 caractères : l'OCR écrasait la couche texte **même en échouant** (`""`) | document réel arrivé **vide** en base si Tesseract manque ou que la page résiste | l'OCR ne remplace que s'il rend davantage |
>
> **Le bump markitdown est passé sans casse** : `0.0.1a3` → **`0.1.6`**, stable. Piège évité
> grâce au filet : depuis la 0.1.0 les formats sont derrière des **extras**, le paquet nu ne
> lit plus ni PDF, ni Word, ni Excel. D'où `markitdown[docx,pdf,pptx,xlsx]`. Excel est le
> canari — c'est le seul format sans aucun fallback dans `extraction.py`. Coût mesuré de
> l'image : **1,16 Go → 1,2 Go** (+~40 Mo ; `magika`/`onnxruntime` arrivent, mais `pandas` et
> `numpy` étaient déjà là).
>
> **Pool dédié, et non `run_in_threadpool`** : ce dernier partage le threadpool AnyIO (40
> jetons) qui sert AUSSI tout endpoint `def` — dont `/sante`. Une rafale d'ingestions y aurait
> repris des jetons au healthcheck, et on retombait sur la même indisponibilité, en plus
> discret. `ETL_EXTRACTIONS_PARALLELES` (défaut 2) borne l'extraction sans jamais toucher au
> reste.
>
> **Le test du healthcheck monte un vrai uvicorn**, pas un `TestClient`. Avec `TestClient` (ou
> `httpx.ASGITransport`) le client vit DANS la boucle qu'on mesure : si elle gèle, le client
> gèle avec elle et l'attente devient invisible — le test serait passé au vert sur le code
> d'avant. Discrimination vérifiée en remettant l'ancien appel : `/sante` **2,99 s** contre
> quelques millisecondes après correction, seuil à 1 s.
>
> **✅ LIVE sur le HP le 2026-07-28** (`5a9e6c5`) — brique rebuildée, 63 conteneurs healthy,
> aucun `unhealthy`. La panne a été **prouvée avant correction**, pas seulement décrite : le
> conteneur a été repassé à l'appel synchrone d'avant-S212 (`docker exec -i`, `docker restart`,
> code vérifié dans `/app/main.py`), puis le **même document** — un PDF de 96 pages sans couche
> texte, entièrement à océriser — a été ingéré des deux côtés.
>
> | Le même PDF de 96 pages | AVANT (appel synchrone) | APRÈS (pool dédié) |
> |---|---|---|
> | `/sante` pendant l'OCR | **> 10 s** (5 sondes consécutives en timeout) | **1,4 à 5,1 ms** |
> | `FailingStreak` Docker | 1 → 2 → **3** | **0** |
> | Statut du conteneur | **`unhealthy` à t+130 s** | `healthy` du début à la fin |
> | Caractères extraits | 145 150 | 145 150 |
>
> Le travail aboutissait dans les deux cas : c'est bien la plateforme qui déclarait l'échec.
>
> | Autre preuve LIVE | Résultat |
> |---|---|
> | `.xlsx` ingéré après le bump | `## Sheet \| Griffon-Sextant-42 chiffre affaires \|` — Excel tient |
> | `.docx` ingéré après le bump | `Griffon-Sextant-42 devis toiture Martin` |
> | `.txt` contenant `\x00`/`\x07` | `abGriffon-Sextant-42 texte brut` — plus de mojibake UTF-16 |
> | `PATCH /classement` puis `GET /dossiers` | `{"projets":{"Toiture Martin":1},…}` |
> | `GET /documents?projet=Toiture%20Martin` | `['note.docx']` ; filtre bidon → `[]` |
> | `audit._recuperer_tous_ids()` | 25 documents (contrat S211 intact) |
> | `GET /assistant/dossiers` (Cœur) | 200 |
>
> Les 10 documents créés par ces tests ont été supprimés après coup (35 → 25, dossiers rendus
> à leur état d'origine).
>
> **Limite assumée** : `stockage.sauvegarder` reste appelé dans la boucle sur les deux chemins
> d'ingestion. C'est un `INSERT` SQLite, de l'ordre de la milliseconde ; sur un texte de
> plusieurs dizaines de Mo il peut coûter une centaine de millisecondes. Loin des 10 s du
> healthcheck, donc laissé tel quel plutôt que d'ajouter un aller-retour de thread par document.

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

> **✅ FAIT le 2026-07-28 — décision : (b) la sortir.** ADR
> `docs/decisions/2026-07-28-app-builder-hors-stack.md`. Dépôt d'accueil publié **public**
> sous Apache-2.0 : https://github.com/toussaintgarinat-crypto/strategic-app-builder
> (`2638c9f` + `da9539d`) — scan de secrets fait avant publication, rien en dur.
> `briques/app-builder/`
> supprimée, 6 références retirées. `make smoke` **990 ✓** (994 → 990 : les 7 tests
> paramétrés sur app-builder disparaissent, 4 passés + 3 skips), `make test-core` **527 ✓**
> inchangé, brique `generateur` **22 ✓** en conteneur.
>
> **Le motif retenu n'est pas l'hébergement, c'est la Gateway.** Servir un HTML statique est
> trivial ; ce qui coûtait, c'était les **16 fournisseurs d'IA appelés en direct depuis le
> navigateur**, clés en `localStorage`. Le servir sur le mesh transformait un défaut personnel
> en exposition réelle, et le corriger imposait de réécrire toute sa couche LLM — l'essentiel
> des ~2 jours de l'option (a), plus un couplage définitif. Sorti, le défaut redevient ce qu'il
> est : le régime normal d'un outil mono-poste, écrit noir sur blanc dans son README.
>
> **Vérifié plutôt que supposé** : aucune brique ne déclare ses offres (`generation_app`,
> `audit_entreprise`, `dashboard`) en `besoin` — la retirer ne casse rien. Et l'affirmation du
> backlog « aucune référence à la Gateway `:5100` » **tient** : les 5 occurrences de `5100`
> dans le fichier sont la couleur CSS `#e65100`.
>
> Le symptôme était d'ailleurs déjà dans `core/conscience.py` : `generateur` et `app-builder`
> y portaient le **même** organe, « mains (fabrication d'applications) », mot pour mot.
>
> Les trois défauts d'ouverture corrigés dans le dépôt d'accueil (manifeste PWA réel + icône,
> version unique `3.0.0`, fichier renommé `index.html`), plus un quatrième non listé : le
> `favicon.ico` absent faisait un 404 à chaque chargement. Vérifié au navigateur après
> extraction — la page démarre, le projet de démo se charge, plus aucune erreur console hormis
> l'avertissement Babel, documenté comme limite assumée avec la dépendance unpkg.com.
>
> **Différence assumée avec le précédent Calendrier Familial** : là-bas la brique `agenda`
> **restait** dans Workplace comme source de vérité, d'où `scripts/export-standalone.sh`. Ici
> c'est une sortie sèche — pas de script de synchro, le dépôt d'accueil devient la seule source.
>
> **Constat de passage, hors périmètre** : 6 des 8 fichiers `test_*.py` de `briques/generateur/`
> ne contiennent aucun test pytest — ce sont des scripts autonomes (`def run()` + `__main__`).
> Le filet réel de la brique est donc de 22 tests, pas de ce que le nombre de fichiers laisse
> croire. Non traité ici : ça mérite sa propre décision.

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

> **✅ CODÉ + PROUVÉ EN CONTENEUR le 2026-07-28.** Brique `briques/connecteurs/` (port 6200),
> 64 tests hors-ligne + 9 tests d'intégration réels. ADR :
> `docs/decisions/2026-07-28-connecteurs-pyairbyte-venv-isole.md`.
> **⚠ Le critère de sortie n'est atteint qu'à moitié** — détail plus bas.
>
> **La prémisse du backlog était fausse.** « PyAirbyte, une simple librairie Python » : c'est
> une lib **grasse et inco-installable** avec le parc. Prouvé avant d'écrire une ligne :
>
> ```
> $ pip install --dry-run 'airbyte==0.53.2' 'fastapi==0.115.6' 'pydantic==2.9.2'
> ERROR: ResolutionImpossible
> ```
>
> `airbyte` tire `fastmcp>=3` → `starlette>=1.0.1` + `pydantic>=2.11.7`, quand
> `constraints-workplace.txt` fige `fastapi==0.115.6` (→ starlette <0.42). Toutes les
> versions ≥0.30 traînent `fastmcp`. `pip install airbyte` seul = **703 Mo** de
> site-packages (il embarque *tous* ses backends de cache : duckdb, snowflake, bigquery,
> postgres). Image finale : **1,32 Go**, la plus grosse du parc.
>
> **Décision** : PyAirbyte vit dans `/opt/pyairbyte` (venv étanche) et n'est joint qu'en
> **sous-processus**, contrat JSON. La cloison rend deux services qu'il aurait fallu bâtir
> de toute façon : la boucle d'événements ne bloque jamais (le défaut que S212 a corrigé sur
> `etl` ne peut pas se produire ici), et un connecteur tiers qui plante n'emporte pas la
> brique. Image `python:3.11-slim` et pas 3.12 : plusieurs connecteurs PyPI exigent `<3.12`
> (`source-stripe`, `source-declarative-manifest`).
>
> **Preuves LIVE en conteneur (2026-07-28)** :
>
> | Ce qui est prouvé | Mesure |
> |---|---|
> | Fail-closed sans coffre | création de source → **503**, refus d'écrire un identifiant en clair |
> | Chiffrement au repos | la config n'est **pas** lisible dans les octets de `/data/connecteurs.db` |
> | Connecteur réel installé | `source-faker` 7.2.1, `check` OK en 58 s (venv créé sur le **volume**) |
> | Sync réelle | 300 enregistrements, curseur recopié dans SQLite |
> | **Non-blocage** | route `202` en **15 ms** pendant une sync de 11 s ; `/sante` à **2-3 ms** pendant le transfert |
> | Interruption | conteneur redémarré en plein transfert → sync passée de `en_cours` à **`interrompue`**, curseur survivant |
> | État repassé au connecteur | fichier `--state` de PyAirbyte **non vide** au 2ᵉ tour (test d'intégration) |
>
> **✅ LE DELTA EST PROUVÉ — et la première conclusion était fausse.** J'ai d'abord écrit
> que « la réduction du delta est une propriété du connecteur, que `source-faker`
> n'implémente pas ». C'était **une erreur de configuration de ma part**.
>
> `source-faker` porte une option **`always_updated`, à `True` par défaut** : *« setting
> this to false will cause the source to stop emitting records after COUNT records have
> been emitted »*. À `True` il régénère tout à chaque passage — il écrit son curseur, rien
> ne diminue, et l'incrémental **paraît** cassé alors qu'il fonctionne.
>
> Chemin parcouru avant de trouver (instructif, d'où sa trace) : 4 variantes de manifeste
> déclaratif (`step`, `cursor_granularity`, `is_client_side_incremental`) → même résultat ;
> catalogue configuré vérifié (`sync_mode=incremental` ✓) ; fichier `--state` vérifié non
> vide ✓ ; puis **connecteur piloté à la main, PyAirbyte hors circuit, état écrit à la
> main → 300 enregistrements quand même**. Ce dernier test a innocenté la plomberie et
> renvoyé vers le `spec` du connecteur. **Leçon : lire le `spec` AVANT de soupçonner sa
> propre plomberie.**
>
> Avec `always_updated: False`, tenu par un test d'intégration :
> **tour 1 = 300, tour 2 = 0**, curseur inchangé ; `complet=true` retransfère bien 300.
>
> **⚠ CE QUI N'EST TOUJOURS PAS TENU : la reprise en cours de sync.** Cette fois ce n'est
> pas de la configuration — c'est le modèle d'écriture de PyAirbyte. Mesuré deux fois, avec
> `records_per_slice: 1000` (donc des `STATE` fréquents côté connecteur) :
>
> | Sync | Tuée après | État survivant | 2ᵉ passage |
> |---|---|---|---|
> | 120 000 enreg. | 35 s | **`{}`** | 120 000 (tout) |
> | 400 000 enreg. | 120 s | **`{}`** | 400 000 (tout) |
>
> PyAirbyte lit la source dans des fichiers de lot puis traite le lot vers le cache, et
> n'écrit l'état qu'**au terme** de ce traitement. Un processus tué avant la fin ne laisse
> aucun point de reprise. **Ni perte ni doublon** (curseur intact, écriture en `merge`),
> mais **le travail est perdu** : la sync suivante repart du dernier curseur *complété*.
> Correct, pas efficient. Sans conséquence pour une sync quotidienne de quelques minutes ;
> douloureux pour un premier plein de plusieurs heures. C'est le principal argument qui
> ferait rouvrir l'option « protocole Airbyte en direct » (ADR).
>
> **Bilan honnête du critère de sortie** : moitié gauche (delta, état vérifié) **atteinte
> et testée** ; moitié droite (reprise en cours de sync) **non atteinte, limite documentée
> de PyAirbyte**, pas un défaut de la brique.
>
> **Piège de déploiement** : sans `VAULT_SECRET` **ni** `CONNECTEURS_ENCRYPTION_KEY` dans le
> `.env` racine, toute création de source répond 503. C'est voulu, mais il faut le savoir
> avant de déployer sur le HP (le `.env` du poste n'a ni l'un ni l'autre).

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

> **✅ FAIT le 2026-07-28.** Décisions consignées dans
> `docs/decisions/2026-07-28-renommage-etl-en-ingestion.md`.
>
> **Ce que le périmètre n'avait pas vu.** Le backlog annonçait « tout est mécanique sauf le
> volume ». Il y avait en fait **deux** pertes de données silencieuses empilées, pas une :
>
> 1. le **volume** change de nom (`etl_etl_data` → `ingestion_ingestion_data`, le nom de
>    projet Compose vient du dossier) → `up` part sur un volume VIDE ;
> 2. le **fichier** change de nom DANS le volume (`etl.db` → `ingestion.db`) → même volume
>    recopié, `sqlite3.connect` crée une base vide à côté de l'ancienne.
>
> Aucune des deux ne lève d'erreur : la brique démarre, le healthcheck passe, `/sante`
> répond `documents_ingeres: 0`. D'où **deux** correctifs, dont aucun ne remplace l'autre :
> `scripts/migration_etl_vers_ingestion.sh` (traverse les volumes, refuse d'écraser une base
> en service, laisse l'ancien volume comme retour arrière) et
> `stockage.reprendre_base_heritee()` (renomme dans le volume, câblée au démarrage).
>
> **Le point tranché, et ce n'est pas celui qu'on attendait** : pas de repli
> `os.getenv("INGESTION_API_KEYS") or os.getenv("ETL_API_KEYS")`. Un repli ne fait pas
> « marcher quand même », il maintient une brique fermée par une variable dont plus rien
> dans le dépôt ne parle — jusqu'au jour où quelqu'un nettoie la ligne orpheline du `.env`
> et rouvre la brique sans le savoir. Sans repli, la panne est courte et connue (fenêtre
> ouverte entre le pull et l'édition du `.env`, réseau Docker, garde SSRF S211 en place)
> plutôt que durable et invisible. **Le `.env` du HP se renomme dans la même opération que
> le `git pull`.**
>
> Renommés aussi, au-delà du périmètre annoncé : les **3 capacités** du manifeste
> (`ingestion_*` — ce sont les noms d'outils vus par l'assistant), le `role` du manifeste,
> qui pilotait la **classe CSS du badge** du dashboard (`.role-etl`) et sa table de
> libellés, et la clé de `core/conscience.py` (table des « organes »). Non renommé, assumé :
> les entrées **datées** du journal de `WORKPLACE.md` et les rapports de sprint archivés —
> réécrire un compte-rendu daté, ce n'est pas le mettre à jour.
>
> Preuves : `briques/ingestion/test_reprise_base_heritee.py` (4 cas, dont un démarrage
> complet par `TestClient`), 51 tests verts sur `ingestion` + `audit` + Cœur, filet de
> contrat des 242 capacités toujours vert, `bash -n` sur le script de migration.

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
| **S210** ✅ | Contrat manifeste ↔ route | capacité morte + 5 dérives silencieuses | ~1 j | — |
| **S211** ✅ | ETL : auth + SSRF + plafond | trou de sécurité exploitable | ~1 j | — |
| **S212** ✅ | ETL : OCR non bloquant, markitdown, classement | indisponibilité + alpha en position critique | ~1 j | S210 |
| **S213** ✅ | app-builder : servir ou sortir | ambiguïté du repo + clés en `localStorage` | 0,5-2 j | — |
| **S214** ⚠ | Brique `connecteurs` (PyAirbyte) | *valeur neuve* | ~3-4 j | après S210 |
| **S215** ✅ | Renommer `etl` → `ingestion` | confort + 2 pertes muettes évitées | ~0,5 j | S214 |

Total ~7 à 9 jours. S210 et S211 sont les deux seuls que je ferais **sans attendre** :
l'un répare des capacités qui ne marchent pas, l'autre ferme une porte ouverte.

---

## SLIVE 2026-07-28 — S213 + S214 déployés sur le HP

`git pull` du HP de `5a9e6c5` → **`eaf3665`** (6 commits : S212 fin, S213, S214).

**Prérequis posé avant le build** : le `.env` du HP n'avait **ni** `VAULT_SECRET` **ni**
`CONNECTEURS_ENCRYPTION_KEY` → la création de source aurait répondu 503. Clé **dédiée**
générée (`openssl rand -hex 32`) et ajoutée au `.env` ; **pas** `VAULT_SECRET`, pour ne rien
changer au comportement de l'agenda (dont le chiffrement retombe dessus à défaut de clé
propre). Sauvegarde du fichier d'origine : `~/workplace/.env.avant-s214`.
⚠ **Cette clé est à sauvegarder** : sans elle, les configs de source déjà chiffrées sont
définitivement illisibles.

**Preuves LIVE sur le HP** :

| | |
|---|---|
| Brique | `workplace_connecteurs` **healthy**, `/sante` → `pont_pyairbyte: true` |
| Découverte par le Cœur | **39/39 briques ok**, les 6 capacités `connecteurs_*` exposées (248 capacités au parc) |
| Connecteur réel | `source-faker` 7.2.1 installé, `check` OK |
| **Delta** | sync n°1 = **300** enregistrements, sync n°2 = **0**, curseur `loop_offset: 300` |
| Non-blocage | route `202` en **3,5 ms**, `/sante` en **1,2 ms** pendant le transfert |
| **Tâche horloge** | déclenchée d'elle-même à 13:18:30, statut `ok`, prochaine échéance J+1 |
| **Garde d'idempotence** | le POST manuel est tombé sur la sync de l'horloge → `deja_en_cours: true` au lieu d'ouvrir une seconde sync |

Les deux dernières lignes n'étaient pas planifiées : l'horloge a tiré pendant la preuve, ce
qui a éprouvé en conditions réelles la tâche déclarée au manifeste **et** la garde
d'idempotence. Source de preuve supprimée ensuite (sinon sync quotidienne inutile).

S213 est passée sans casse : `briques/app-builder` retirée du disque, aucun conteneur ne
l'utilisait. Disque du HP : 87 Go / 327 Go utilisés (l'image `connecteurs` pèse 1,32 Go).

---

## SLIVE 2026-07-28 — S215 déployé sur le HP

Le dernier sprint du lot. Les six sont désormais LIVE.

**L'ordre était le sujet, pas le renommage.** La seule vraie difficulté du déploiement tenait
en une contrainte : la brique est fermée par une clé dont le NOM change, et son volume change
de nom en même temps. Séquence tenue, et elle a supprimé la fenêtre ouverte que l'ADR
annonçait comme risque accepté :

1. **`.env` d'abord, avant le `git pull`** — renommer `ETL_KEY`/`ETL_API_KEYS` en
   `INGESTION_*` (mêmes valeurs, `diff` des secrets à l'appui). Les conteneurs en cours ont
   lu leur environnement au démarrage : les renommer sur disque ne les dérange pas. Résultat :
   au moment du `up`, les nouveaux noms sont **déjà en place** → **fenêtre ouverte = zéro**,
   là où l'ADR tablait sur « courte et bornée ». À refaire dans cet ordre.
2. **`docker compose down` de l'ancienne brique AVANT le pull** — après le pull, son dossier
   n'existe plus et le conteneur devient un orphelin qu'aucun compose ne pilote.
3. `git pull` → `scripts/migration_etl_vers_ingestion.sh` → `up -d --build`.

**Preuves LIVE** :

| | |
|---|---|
| Baseline avant migration | `{"service":"etl","documents_ingeres":25}`, base de 1,18 Mo |
| Après migration | `{"service":"ingestion","documents_ingeres":25}` — **25 documents transportés, 0 perdu** |
| Fermeture effective | `GET /documents` sans clé → **401** ; avec la clé du `.env` → 200, 25 documents |
| Cœur → brique fermée | `/assistant/dossiers` rend `{"prochain sprint":1}` + 4 catégories, **identique** à l'appel direct avec clé → `INGESTION_KEY` est bien portée |
| `audit` → brique fermée | `INGESTION_URL=http://host.docker.internal:5200`, en-tête porteur d'une clé : `True` |
| Registre du Cœur | **39/39 briques ok**, `ingestion` présente, `etl` **absente** |
| Conteneurs | tous `healthy`, 64 conteneurs, disque 87 Go / 327 Go |
| **Capacités vues par l'assistant** | les 3 `ingestion_*` exposées (248 au parc), les 3 `etl_*` disparues |
| **Écriture réelle** | `POST /ingerer` → extraction → relecture du texte → compteur 25→26 → suppression → 25. Le chemin d'écriture, pas seulement la lecture |
| `audit` → lecture effective | `_recuperer_tous_ids()` rend **25 ids** et `_recuperer_textes()` rend le contenu, à travers la brique fermée |
| Badge du dashboard | `.role-ingestion` présent (×1) et `.role-etl` absent dans le fichier servi ; libellé `ingestion:'Ingestion'` ; registre → `role: ingestion` |

**Détail imprévu, sans gravité** : `git pull` ne supprime pas `briques/etl/` parce que le
`__pycache__` qu'il contient est **non suivi et appartient à root** (écrit par le conteneur).
Le dossier survit au renommage, vide de tout code mais visible. Retiré au `sudo`.

**Filet de retour arrière laissé en place** : le volume `etl_etl_data` et l'image
`workplace-etl:0.1.0` existent toujours. À supprimer quand la brique aura quelques jours de
vol — `docker volume rm etl_etl_data`. Tant qu'ils sont là, le retour arrière coûte un
`git revert` et un `up`.

**Les deux derniers maillons, rejoués ensuite** — il ne reste rien de « ça devrait marcher » :

| | |
|---|---|
| **Le LLM appelle la capacité renommée** | `POST /assistant/chat` → événement `{"type":"outil","nom":"ingestion_documents_lister","brique":"ingestion"}`, résultat `total: 25`, réponse rendue : « Il y a **25 documents** ingérés au total. » |
| **Audit LLM complet** | `POST /auditer` sur les 4 documents « Menuiserie Lefèvre » → `termine` en **65 s**, les **4 couches** remplies de contenu réel (DDD/bounded contexts, VSM, Ishikawa, chemin critique). Documents lus à travers la brique **fermée par clé**. Audit de test supprimé ensuite (18 → 17), relecture → 404. |

L'audit a été **borné à 4 documents** au lieu des 25 : même chaîne LLM à 4 couches, une
fraction du coût. Rien dans le renommage ne dépend du nombre de documents.
