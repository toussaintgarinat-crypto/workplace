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
3. Au moment de payer, chacun règle **sa part** : en ligne (paiement **mock honnête** en
   incrément 1, marqué « démo »), ou **en espèces** validées par le restaurateur. La
   tablette et les clients voient le **« reste à payer »** bouger en direct.

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
| `GATEWAY_URL` / `GATEWAY_KEY` / `GATEWAY_MODEL` | LLM de structuration de la carte | Gateway / vide / modèle gratuit |

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
