# Guide — brancher Stripe **réel** sur Forge (encaissement en ligne)

> **Statut : documentation. Le code S21 est livré et prouvé _offline_ ; ce guide est
> ce qu'il reste à faire pour passer en _live_.** Tant qu'aucune clé n'est posée, le
> checkout reste en `mode:"mock"` (dégradation honnête, aucun encaissement réel).
> Voir `docs/sprints/S21-forge-stripe-reel.md`.

## 0. À savoir avant (honnêteté technique)
- **Commence en mode TEST** (`sk_test_…`, carte `4242 4242 4242 4242`). Le passage
  `sk_live_…` se fait à l'identique une fois le flux validé.
- **Deux secrets distincts**, ne pas les confondre :
  - **Clé secrète** `sk_test_…` → sert à *créer* les sessions de paiement (checkout) ;
  - **Secret de webhook** `whsec_…` → sert à *vérifier la signature* des événements Stripe.
- Le **webhook est la pièce sensible** : sans `whsec_…` configuré, l'endpoint **refuse**
  (503) — c'est volontaire (on ne réintroduit pas le trou du mock où n'importe qui
  pouvait marquer un paiement « payé »).

## 1. Récupérer les clés Stripe (mode test)
1. Crée/ouvre un compte sur https://dashboard.stripe.com (bascule **« Test mode »** en haut).
2. **Developers → API keys** → copie la **Secret key** `sk_test_…`.
3. Le secret de webhook `whsec_…` s'obtient à l'étape 4 (Stripe CLI le génère).

## 2. Poser la clé secrète au **coffre chiffré** (voie recommandée)
La clé est stockée **chiffrée** en base (AES-256-GCM, `crypto.py`), jamais en clair.
Deux façons :

**a) Via l'UI Forge** (la plus simple) : dashboard `:5100` → onglet **Forge** →
**Settings → API keys** → fournisseur **« Stripe (clé secrète) »** → colle `sk_test_…` → enregistrer.
(Le provider `stripe` a été ajouté à la liste en S21.)

**b) Via l'API** (si tu préfères curl) — il faut un **jeton utilisateur** Keycloak du realm
`oria` (celui de ta session Forge ; récupère-le dans les DevTools du navigateur, en-tête
`Authorization`) :
```bash
curl -X PUT http://localhost:8600/api/settings/api-keys/stripe \
  -H "Authorization: Bearer <TON_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"key":"sk_test_..."}'
# → {"ok":true,"hint":"sk_t••••••••••••XXXX"}
```

> **Repli env** (si tu ne veux pas du coffre) : poser `STRIPE_SECRET_KEY=sk_test_…` dans
> `briques/forge/.env`. Le coffre a la priorité ; l'env sert de repli (parité keystore).

## 3. Configurer le secret de webhook + les URLs (env)
Édite `briques/forge/.env` :
```bash
STRIPE_WEBHOOK_SECRET=whsec_...                       # obtenu à l'étape 4
STRIPE_SUCCESS_URL=http://localhost:3000/paiement/succes
STRIPE_CANCEL_URL=http://localhost:3000/paiement/annule
```
Puis **recrée** le conteneur core (un `restart` ne relit pas `.env`) :
```bash
cd briques/forge && docker compose up -d --force-recreate forge
```

## 4. Écouter les webhooks en local (Stripe CLI)
En dev, ton `localhost` n'est pas joignable par Stripe → la **Stripe CLI** relaie les
événements et **te donne le `whsec_…`** :
```bash
brew install stripe/stripe-cli/stripe     # une fois
stripe login                              # ouvre le navigateur
stripe listen --forward-to localhost:8600/api/stripe/webhook
# ⬅ affiche : « Ready! Your webhook signing secret is whsec_xxx »
```
Copie ce `whsec_…` dans `briques/forge/.env` (étape 3) et recrée le core.
Laisse `stripe listen` **tourner** pendant les tests.

> **En production** : pas de CLI. Crée l'endpoint dans **Dashboard → Developers →
> Webhooks** pointant vers l'URL publique `https://<ton-domaine>/api/stripe/webhook`,
> et utilise le `whsec_…` affiché là. L'endpoint doit être **joignable depuis Internet**.

## 5. Vérifier que Stripe est bien « réel »
Demande à l'assistant **« est-ce que les paiements Stripe sont configurés ? »**
(outil `forge_paiement_etat`) → il doit répondre **configuré, mode `test`** (et non `mock`).
Ou en direct :
```bash
curl http://localhost:5700/paiement/etat
# → {"configure":true,"mode":"test","indice_cle":"sk_t••••XXXX","webhook_verifie":true,...}
```

## 6. Test de bout en bout (carte 4242)
1. **Créer le lien** : à l'assistant « crée un lien de paiement pour le plan pro »
   (outil `forge_paiement_lien`, confirmé) → renvoie une **vraie** `checkout.stripe.com/…`.
2. **Payer** : ouvre le lien → carte `4242 4242 4242 4242`, date future, CVC quelconque.
3. **Webhook** : `stripe listen` relaie `checkout.session.completed` → le core **vérifie la
   signature** → le `StripePayments` passe à `complete`.
4. **Constater** : « montre mon historique de paiements » → le paiement apparaît `complete`.

## Récapitulatif — où va quoi
| Secret | Où | Rôle |
|---|---|---|
| `sk_test_…` | **coffre chiffré** (provider `stripe`) ou `STRIPE_SECRET_KEY` (env, repli) | créer les sessions de paiement |
| `whsec_…` | `STRIPE_WEBHOOK_SECRET` (env) | **vérifier la signature** des webhooks |
| `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` | env | redirections post-paiement |

## Quand tu seras prêt pour le **live**
- Bascule le Dashboard en mode **live**, récupère `sk_live_…` + un nouveau `whsec_…`
  (webhook live distinct), remplace-les (coffre + env), recrée le core.
- Active d'abord un vrai compte (informations société, IBAN) côté Stripe.
- Garde un œil sur l'idempotence si tu ajoutes d'autres événements
  (`invoice.paid`, `customer.subscription.*`) — repoussés hors-scope en S21.
