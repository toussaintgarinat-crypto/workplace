# Brique `restaurant` — commande & paiement à table par QR

Produit autonome (port **6010**) : un restaurateur crée un compte, gère un ou plusieurs
restaurants **totalement cloisonnés**, et ses clients commandent + paient à table en
scannant un QR code. Inspiré de Sunday / Skeat, mais souverain (rien ne sort vers un tiers).

## Les trois surfaces

| Surface | URL | Auth |
|---|---|---|
| **Back-office** restaurateur | `/` | compte (email + mot de passe) |
| **Cuisine** (plein écran) | `/cuisine?resto=<id>` | session du back-office |
| **Client** (ouvert par le QR) | `/carte/<code>` | aucune — le code de table fait *capability* |

## Le parcours

1. Le restaurateur compose sa **carte** (prix éditable, photo prise au téléphone,
   bascule *Disponible* pour les ruptures, *Plat du jour*) et crée ses **tables** → un
   **QR code** par table (généré **localement**, `segno`, jamais un service tiers).
2. Le client **scanne**, choisit son **prénom / numéro de siège**, commande. La commande
   part en **cuisine en temps réel** (WebSocket), étiquetée table + convive.
3. Au moment de payer, l'addition se règle par **répartition flexible** (v0.9.0) : **chacun
   sa part**, **partage égal** en N convives, ou **montant libre** — en ligne (paiement
   **mock honnête** en incrément 1, marqué « démo »), ou **en espèces** validées par le
   restaurateur. La tablette et les clients voient le **« reste à payer »** bouger en direct.

## Prêt pour la vente (v0.2.0)

- **Clôture de table** : « Clôturer la table » archive un **ticket** et remet la table à
  zéro → le groupe suivant repart vierge (les sessions sont cloisonnées). Refuse s'il
  reste à payer, sauf `force` (départ assumé par le resto).
- **TVA & ticket** : taux de TVA réglable par restaurant, **ventilation HT/TVA** sur
  l'addition, **ticket imprimable**.
- **Sécurité prod** : sessions **révocables** (changer le mot de passe ou « déconnecter
  tous les appareils » invalide les anciens jetons), **anti-brute-force** sur les routes
  d'auth, refus de démarrer en prod avec le secret de dev (`RESTAURANT_ENV=prod`).
- **Confort** : **catégories** de carte (Entrées/Plats/Boissons…), **pourboire** optionnel.

Restent hors-code (pas de notre ressort) : **paiement réel** (Stripe Connect Express,
incrément séparé) et **hébergement HTTPS** (Proxmox/cloud + domaine).

## Assistant carte & pilotage par le Cœur (v0.4.0)

Trois surfaces complémentaires pour **gérer la carte avec un assistant** — utile surtout à
l'**onboarding d'un nouveau restaurant**.

- **Importer une ancienne carte** (onglet du back-office) : le restaurateur **photographie /
  dépose** son ancienne carte → la brique délègue l'**OCR** à la brique [`vision`](../vision)
  puis la **structuration** (plats : nom / prix / catégorie) au LLM de la **Gateway** → propose
  une carte **éditable**. Le restaurateur corrige, puis **« Ajoute à ma carte »** (création en
  lot). Rien n'est écrit avant validation. Repli **honnête** : OCR illisible ou briques
  éteintes ⇒ proposition vide + la raison, jamais de plat inventé.
  Endpoints (session) : `POST /restaurants/{id}/carte/importer` (propose), `POST …/plats/lot`.
- **Générer une carte** : pas d'ancienne carte ? Le restaurateur **décrit son concept**
  (cuisine, ambiance, gamme de prix) → le LLM Gateway **génère une carte complète** structurée
  par sections, prix réalistes en centimes → même flux éditable → ajout. Repli honnête (vide +
  raison). Endpoint (session) : `POST /restaurants/{id}/carte/generer`.

- **Carte pilotable par l'assistant / MCP** : le manifest déclare des `capacites`
  (`restaurant_carte_lister`, `restaurant_infos`, `restaurant_plat_ajouter / _modifier /
  _supprimer`) → découvertes automatiquement par le Cœur (S63/S64) et exposées via son
  Gateway MCP (S74). Le Jarvis (voix/chat) ou un client MCP peut donc **gérer la carte**
  (« ajoute un tartare à 16,50 € au restaurant X »). Chemin de **service** `/service/...`
  authentifié par clé `RESTAURANT_KEY` (en-tête `X-API-Key`), scoppé par `restaurant_id`.
  **Fail-closed** : sans `RESTAURANT_KEY`, le chemin de service est **éteint** (503).

> Limite honnête (mono-utilisateur aujourd'hui) : qui détient `RESTAURANT_KEY` peut viser
> n'importe quel `restaurant_id` via le Cœur. Le cloisonnement reste tenu **en base** (chaque
> opération passe par le compte propriétaire dérivé du resto) ; l'**isolation par restaurateur
> côté Cœur** relève de l'épopée multi-tenant à venir.

## La soirée : surnom, tournée, souvenir & annulation (v0.11.0)

Quatre touches pour rendre le service plus humain — trois côté convives, une côté cuisine.

- **🏷️ Renommer la tablée** — les convives donnent un **surnom rigolo** à leur table
  (« Les Gloutons », « La Joyeuse Marmite »…) depuis la page **Addition**. C'est un
  **souvenir** affiché côté client (pas imprimé sur le ticket fiscal). Stocké sur la session
  courante (`tables.nom_session`), **effacé à la clôture** comme le PIN → le groupe suivant
  repart vierge. `POST /t/{code}/nommer` (nom vide = retirer), diffusé en direct à la table.
- **🍻 Je paye ma tournée** — un convive règle **tout le reste de la table** d'un clic +
  message festif. Nouveau `mode=tournee` de `domaine.montant_a_encaisser` (vise = reste global),
  donc **toujours borné** au reste réel (anti-surpaiement inchangé). Passe par le même
  `POST /t/{code}/payer`.
- **📜 Souvenir de soirée** — en fin de repas, un petit récap (surnom + plats partagés + total).
  Ton festif **délégué au LLM** via la Gateway (`souvenir.py`, modèle gratuit par défaut), avec
  **repli FACTUEL local honnête** si l'assistant est hors ligne — `genere_par` dit toujours la
  vérité (`ia` / `local`), **aucune anecdote inventée**. `GET /t/{code}/resume?lang=fr`.
- **🗑️ Annuler une commande en cuisine** — le **staff** retire une commande déjà envoyée
  (erreur de saisie, annulation client) depuis l'écran cuisine. **Retrait simple** : la commande
  sort de la file **et** de l'addition (stock **non** recrédité, pas de trace — choix produit).
  `DELETE /restaurants/{id}/commandes/{commande_id}`, **réservé au propriétaire** (404 sur le
  resto d'autrui), diffusé aux écrans cuisine et à la table.

## Avis clients par QR (v0.10.0)

Le client laisse un **avis** (note **1–5 ⭐ + commentaire** optionnel) directement depuis la page
**Addition** de l'app de table — donc **via le QR**, sans compte, sans appli à installer. Le
restaurateur retrouve la **synthèse** dans un onglet **« Avis »** du back-office : **moyenne**,
nombre, et les derniers commentaires.

- **Souverain / interne** : aucun service tiers, aucune synchro Google (un *pont* Google Reviews
  resterait un incrément séparé, sur le modèle du pont agenda↔Google).
- **Un avis par convive et par visite** (table + session) : re-soumettre **corrige** le sien
  (upsert), jamais de doublon — index unique `(table, session, convive)`.
- **Note validée serveur** : `domaine.normaliser_note` borne à 1–5 (hors bornes → 400) ;
  `domaine.moyenne_notes` calcule la moyenne (arrondie à une décimale). Règles **pures**, testées.
- **Cloisonné** : `GET /restaurants/{id}/avis` est gardé par le propriétaire (404 sur le resto
  d'autrui). Dépôt client : `POST /t/{code}/avis` (capability du QR, respecte le code de table).

## Répartition flexible de l'addition (v0.9.0)

Jusqu'ici chacun ne pouvait régler que **ses propres plats**. Désormais le client choisit,
sur la page **Addition**, **comment** régler le reste de la table :

- **Chacun sa part** (`mode=part`, défaut historique) — règle le dû propre du convive ;
- **Partage égal** (`mode=egal`, `parts=N`) — divise le **total** en N parts égales ; chacun
  règle une part, le **dernier payeur absorbe le reliquat** → la somme tombe **juste** au
  centime (`1000 / 3 → 334 + 333 + 333`, jamais de centime orphelin) ;
- **Montant libre** (`mode=libre`, `montant_cents`) — « je mets 30 € » sur l'addition commune.

**Invariant clé — anti-surpaiement** : quel que soit le mode, le montant encaissé est
**recalculé serveur** et **toujours borné au reste GLOBAL** de la table. Impossible de payer
plus que ce que la table doit, ni de cumuler deux paiements libres au-delà du total.

Côté **domaine** (`domaine.py` pur, testé en microsecondes) : `parts_egales(total, n)` (partage
exact, résidu sur les premières parts) et `montant_a_encaisser(reste_global, mode, …)` (la
règle de plafonnement, source unique). Exposé par `POST /t/{code}/payer` et
`/restaurants/{id}/tables/{id}/paiement-especes` (mêmes champs `mode`/`parts`/`montant_cents`).

## Rejoindre la table par code (v0.8.0)

Réglage **opt-in** par restaurant (back-office → Réglages) : **« Demander un code pour
rejoindre une table »**. Désactivé par défaut → la table reste **ouverte** (tout scan du QR
commande directement, comportement historique inchangé).

Une fois activé, l'app client présente une **porte** :

- **Démarrer la table** (1er appareil) → génère un **code à 4 chiffres** affiché à l'écran,
  à partager avec la tablée. L'appareil reçoit un **jeton d'adhésion de session**.
- **Rejoindre** (appareils suivants) → saisir le code → jeton d'adhésion (fail-closed sur
  un mauvais code, anti-brute-force par table).

Le code **protège l'addition en cours** : commander, régler et consulter l'addition exigent
le jeton. Plusieurs appareils partagent **la même session** (l'addition est commune). À la
**clôture**, le numéro de session change et le code est effacé → les anciens jetons sont
automatiquement **invalidés** (le groupe suivant repart d'une table vierge).

Côté **domaine** : l'agrégat racine **`SessionDeTable`** (`domaine.py` pur) porte l'identité
`(table, numéro)` + le `code_pin` optionnel et la règle d'autorisation (`autorise(pin)`,
comparaison à temps constant). Le jeton d'adhésion est signé HMAC (`auth.creer_jeton_table`,
lié à `(table, session)`, stateless comme les sessions restaurateur). Réglage exposé par
`PATCH /restaurants/{id}` (`pin_requis`).

## UX client multi-pages & multi-convive (v0.7.0)

L'app client (ouverte par le QR) passe d'un long défilement à une **navigation multi-pages**
avec un **bottom-nav** : **Carte · Panier · Addition**.

- **Carte** : un **accueil en tuiles de catégories** + une **barre de recherche** (filtre tous
  les plats) → une **page catégorie** → une **fiche plat** (photo, description, **format**,
  **quantité**, **« pour qui ? »** et **note** libre par ligne).
- **Multi-convive correct** : un même téléphone peut porter **plusieurs convives** (ex. Thomas
  *et* Sarah). Le convive est choisi **à l'ajout** dans la fiche (« pour qui ? ») — fin du
  « tout sur une seule personne ». Le **Panier** récapitule **par convive** (sous-total chacun,
  notes, renommage), puis « Envoyer en cuisine » crée **une commande par convive** (la cuisine
  et l'addition restent organisées par personne).
- **Addition** : on règle la part de chaque convive porté par l'appareil (mock honnête).

Côté **domaine** (DDD pragmatique, au fil de l'eau) : un module **`domaine.py` PUR** (0 I/O)
pose l'objet-valeur **`Argent`** (centimes + devise), l'entité **`Convive`** (normalisation du
nom, source unique back+front) et le **groupage par convive** d'un panier — testés en
microsecondes (`test_domaine.py`). Une **note** par ligne est persistée (`lignes.notes`,
migration douce) et remonte dans la file cuisine et l'addition.

## Stock & rupture automatique (v0.6.0)

Un plat peut porter un **stock** optionnel (unités restantes). `null` = **illimité** (défaut,
comportement inchangé) ; un entier (ex. « Côte de bœuf : 6 ») est **décompté
ATOMIQUEMENT** à chaque commande (`UPDATE … SET stock = stock - q WHERE stock >= q`), donc
**jamais de survente** même en commandes simultanées. À **0**, le plat **disparaît
automatiquement** de la carte client (et n'est plus commandable → `400`), et porte un badge
**« Épuisé »** au back-office (il n'est pas supprimé : un **réapprovisionnement** le fait
réapparaître). Réglé au back-office (bouton **Stock** : un nombre, ou vide = illimité) et via
les capacités `restaurant_plat_ajouter/_modifier` (param `stock`).

**Temps réel** : une rupture provoquée par une commande est **poussée à toutes les tables
ouvertes** du resto (nouveau canal WebSocket `carte:{restaurant_id}` auquel chaque client
s'abonne en plus de sa table) → la carte se rafraîchit en direct, sans recharger la page.

## Formats / tailles (v0.5.0)

Un plat peut avoir plusieurs **formats** (ex. bière **25cl / 50cl / 1L / girafe 2,5L**), chacun
avec son prix. Le prix de carte affiché devient « **dès** X » (le moins cher). Côté **client**,
chaque taille a sa ligne d'ajout ; à la commande, la **taille choisie** est envoyée et l'addition
enregistre le **nom + prix du format** (snapshot, ex. « Carlsberg (50cl) — 7 € »). Sans formats,
le plat reste à prix unique (comportement inchangé). Édition dans le back-office (bouton
**Formats** : `25cl=3.50, 50cl=7, 1L=13, Girafe 2,5L=28` ; vider = repasser en prix unique) et via
les capacités `restaurant_plat_ajouter/_modifier` (param `formats`). Stockés en JSON sur le plat.

## Multi-tenant (cloisonnement)

`Compte → Restaurant(s) → Tables / Plats / Commandes / Paiements`. Toute lecture/écriture
côté restaurateur exige le compte propriétaire (**fail-closed** : un restaurateur reçoit
un `404` sur le restaurant d'un autre, on ne révèle même pas son existence). Prouvé par
`test_isolation.py`.

## Paiement

Incrément 1 = **mock** assumé (aucun flux d'argent réel, libellé « démo » côté UI). Le
montant est recalculé **côté serveur** (jamais soumis par le client). Incrément suivant :
**Stripe Connect** réel (les fonds vont au restaurateur).

## Réglages (env)

| Variable | Rôle | Défaut |
|---|---|---|
| `RESTAURANT_DB` | chemin SQLite | `/data/restaurant.db` |
| `RESTAURANT_SECRET` | signature des sessions (HMAC) | dev non secret — **à définir en prod** |
| `RESTAURANT_ENV` | `prod` ⇒ refuse de démarrer avec le secret de dev | vide (dev) |
| `RESTAURANT_SESSION_TTL` | durée de session (s) | `2592000` (30 j) |
| `RESTAURANT_MAX_TENTATIVES` | tentatives d'auth par fenêtre de 5 min | `10` |
| `RESTAURANT_PUBLIC_URL` | base d'URL des QR (vue du smartphone) | déduite de la requête |
| `CORS_ORIGINS` | origines navigateur autorisées (CSV) | `*` |
| `RESTAURANT_KEY` | clé de service (pilotage carte par le Cœur/MCP) ; **vide ⇒ /service éteint** | vide |
| `VISION_URL` / `VISION_KEY` | brique OCR pour l'import de carte | `…:5960` / vide |
| `GATEWAY_URL` / `GATEWAY_KEY` / `GATEWAY_MODEL` | LLM (structuration de carte + résumé de soirée) ; repli honnête si absent | Gateway / vide / modèle gratuit |

## Tests

```bash
python -m pytest -q   # auth, isolation multi-tenant, parcours, temps réel, QR,
                      # clôture/TVA/sécurité/catégories/pourboire (test_vendable)
```

## Limites assumées

- Paiement **mock** → Stripe Connect Express dans une brique `paiements` séparée (incrément final) ;
- pilotage par le Cœur câblé via clé de service (mono-utilisateur) ; isolation par restaurateur
  côté Cœur = épopée multi-tenant à venir ;
- l'import de carte dépend de la brique `vision` (OCR) + Gateway (LLM) : sans elles, repli honnête ;
- interface **FR / EN** (extension multilingue ultérieure).
