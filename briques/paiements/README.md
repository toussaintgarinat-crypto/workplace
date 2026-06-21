# Brique `paiements` — le rail d'argent (multi-tenant, Connect)

Brique **autonome** (port **6020**) qui possède le **rail de paiement** : comptes connectés des
vendeurs, encaissement avec **commission plateforme**, remboursements, webhooks signés. Elle est
**réutilisable** par plusieurs solutions (restaurant, Forge, futures marketplaces) — chacune
**isolée par sa clé API**. Le **split / addition partagée** reste dans la brique appelante (ex.
restaurant) ; ici on tient uniquement le **flux d'argent**.

## Pourquoi une brique séparée (et pas dans `restaurant`)

Un restaurateur encaisse **sur son propre compte**. Tout faire transiter par un compte unique
(« je collecte tout puis je rembourse ») est **interdit** par Stripe (transmetteur de fonds non
licencié, merchant of record, bombe TVA). La bonne forme : **Stripe Connect**, où chaque vendeur a
un **compte connecté**, les fonds vont **direct au vendeur**, et la plateforme prélève une
**commission** (`application_fee`). Ce rail vaut pour n'importe quelle solution → une **brique
dédiée**, pas du code noyé dans le restaurant.

## Fournisseurs (provider-agnostique)

| Fournisseur | Quand | Comportement |
|---|---|---|
| **Mock** (défaut) | aucune clé Stripe | **Honnête** : aucun argent ne bouge, tout est étiqueté « mock ». Sert la démo, les tests, le dev souverain. |
| **Stripe** | clé `STRIPE_SECRET_KEY` présente | Réel. **Test** avec une clé `…_test_`, **live** avec `…_live_` (+ validation plateforme Stripe + KYC vendeurs = étape externe). |

Le SDK `stripe` est importé **paresseusement** : le mock et les tests tournent sans lui.

### Bonnes pratiques Stripe suivies
- **Onboarding hébergé** (Account Links) : on ne collecte **aucune PII** nous-mêmes.
- **Controller properties** (pas le label legacy « Express ») : la plateforme assume les pertes et
  les frais, le vendeur a un tableau de bord « express ».
- **Destination charges** : `transfer_data.destination` + `application_fee_amount` (la commission).
- **Webhooks à signature vérifiée** : aucun événement traité sans signature (sinon 503/400).
- **Clé jamais en clair** : ni dans une réponse, ni dans un log, ni dans un message d'erreur. On
  préfère une **clé restreinte** `rk_` (moindre privilège).

## Multi-tenant

La **clé API** (`X-API-Key` ou `Bearer`) identifie la **solution** (le tenant). Le tenant stocké
est l'**empreinte** de la clé (`sha256` tronquée) — la clé reste secrète. Une solution ne voit
**jamais** les comptes/paiements d'une autre (fail-closed, **404**). `API_KEYS` (CSV) liste les
solutions autorisées ; vide = dev ouvert (espace « public » unique).

## API

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/sante` | Santé |
| `GET` | `/config` | État honnête du rail (mock / stripe test / live) |
| `POST` | `/comptes-connectes` | Créer un compte vendeur |
| `GET` | `/comptes-connectes` | Lister ses comptes |
| `GET` | `/comptes-connectes/{id}` | Statut (rafraîchi du fournisseur) + `peut_encaisser` |
| `POST` | `/comptes-connectes/{id}/onboarding` | Lien d'onboarding hébergé |
| `POST` | `/paiements` | Encaisser (montant + commission `bps` ou `cents`) |
| `GET` | `/paiements` · `/paiements/{id}` | Lister / consulter |
| `POST` | `/paiements/{id}/rembourser` | Rembourser (transition gardée) |
| `POST` | `/webhooks/stripe` | Événements Stripe (signature vérifiée) |

La **commission** est recalculée **serveur** et **bornée** à `[0, montant]` (jamais négative ni
supérieure au brut → net ≥ 0). Le statut d'un paiement suit une **machine à états gardée**
(`cree → paye → rembourse`), donc pas de double remboursement ni de remboursement d'un impayé.

## Réglages (env)

| Variable | Rôle | Défaut |
|---|---|---|
| `API_KEYS` | clés des solutions autorisées (CSV) | vide (dev ouvert) |
| `STRIPE_SECRET_KEY` | clé Stripe (préférer `rk_`) ; **vide ⇒ mock** | vide |
| `STRIPE_WEBHOOK_SECRET` | secret de signature des webhooks | vide |
| `PAIEMENTS_PUBLIC_URL` | URL publique (liens d'onboarding) | `http://localhost:6020` |
| `PAIEMENTS_DB` | chemin SQLite | `/data/paiements.db` |
| `CORS_ORIGINS` | origines navigateur (CSV) | `*` |

## Tests

```bash
python -m pytest -q   # domaine pur, isolation multi-tenant, parcours mock complet
```

## Limites assumées (v0.1.0)

- **Mock prouvé** de bout en bout ; le fournisseur **Stripe est écrit selon les bonnes pratiques**
  mais sa preuve **LIVE** exige une vraie clé `sk_test_`/`rk_test_` + un compte plateforme Connect
  (étape externe). Activation **live** = validation Stripe + KYC vendeurs (admin, pas du code).
- Pas encore branchée à la brique `restaurant` (le restaurant garde son paiement mock interne) :
  le **branchement** restaurant→paiements est l'incrément suivant.
- Onboarding mock = page interne qui active le compte (aucun KYC réel — c'est affiché).
