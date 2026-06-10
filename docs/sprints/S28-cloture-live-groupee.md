# S28 — Clôture LIVE groupée (Stripe + emails + comptes)

> **Objectif** : configurer une fois les prérequis communs (SMTP réel, clé Stripe
> `sk_test_`, rôle Keycloak `manage-users` + SMTP du realm `oria`) puis **rejouer
> les 3 flux en LIVE** pour solder d'un coup les dettes S21/S22/S23 (« code livré +
> prouvé offline, reste LIVE »). C'est la chaîne qui rapproche de l'euro :
> devis → facture → paiement → relance → compte client.

**Statut : ✅ LIVRÉ + PROUVÉ LIVE (dev) le 2026-06-10.** Données de test nettoyées.

## Prérequis communs posés

| Prérequis | Ce qui a été fait |
|---|---|
| **SMTP (dev)** | Mailpit lancé (`docker run -d --name mailpit -p 8025:8025 -p 1025:1025 axllent/mailpit`). UI : http://localhost:8025. |
| **SMTP câblé Forge** | Vars `SMTP_*` ajoutées à `briques/forge/.env` (Mailpit, `host.docker.internal:1025`, sans auth/TLS) et référencées dans le compose **actif** `briques/forge/docker-compose.yml` (service `forge`). |
| **Keycloak `manage-users`** | Rôle `realm-management:manage-users` donné au service account `service-account-workplace-provisioner` (kcadm, realm `oria`). |
| **SMTP realm `oria`** | `smtpServer` du realm pointé vers Mailpit via `kcadm update realms/oria -s 'smtpServer={...}'`. |

## Flux 1 — S22 emails & relances ✅

1. Token `forge-service` (client_credentials, realm `oria`) → API Forge `:8600`.
2. Facture créée avec email client → `POST /api/facturation/{id}/envoyer` → **email reçu dans Mailpit** (« Votre facture FACT-… »).
3. 2ᵉ facture, échéance backdatée −20 j → `GET /api/relances/impayes/apercu` = 1 candidat **J+15**.
4. `POST /api/relances/impayes/executer` → 1 relance envoyée (« 2e rappel — facture … échue »), reçue dans Mailpit.
5. **2ᵉ `executer` = 0 envoyée** → anti-doublon `(facture, niveau)` confirmé en LIVE.

## Flux 2 — S23 compte client auto ✅

1. `client_provisioning.creer_compte_client(email, nom, world_id=None, …)` (conteneur `generateur`).
2. **Compte Keycloak créé** (realm `oria`) ; 2ᵉ passage `compte_cree=False` → **idempotence** confirmée.
3. `execute-actions-email` (`UPDATE_PASSWORD` + `VERIFY_EMAIL`) → email **« Update Your Account »** reçu dans Mailpit, contenant le lien `login-actions/action-token`.

🐞 **Bug LIVE trouvé & corrigé** : le défaut `ORIA_URL_PUBLIQUE=http://localhost:8000`
faisait répondre `execute-actions-email` en **400** (redirect_uri absent des
`redirectUris` de `oria-app`, qui autorise `:3000/:3002/:3003/:5173/:5400`).
Correctif persistant dans `briques/generateur/docker-compose.yml` :
`ORIA_URL_PUBLIQUE=http://localhost:3003` (+ `ORIA_URL_INTERNE`, `KEYCLOAK_URL_INTERNE`
explicites). Rejoué **sans override runtime** après recréation → email parti. ✅

## Flux 3 — S21 Stripe ✅

1. Clé `sk_test_…` (fournie par l'utilisateur) → `PUT /api/settings/api-keys/stripe` → **chiffrée au coffre** (indice masqué `sk_t••••GxtX`, jamais en clair).
2. `GET /api/stripe/etat` → `configure:true, mode:test`.
3. **Checkout RÉEL** : `POST /api/stripe/checkout {plan:starter}` → vraie session `cs_test_a1V8…` + `checkoutUrl https://checkout.stripe.com/c/pay/…` ; paiement tracé `pending`.
4. `STRIPE_WEBHOOK_SECRET` posé (`briques/forge/.env`, passé par le compose actif) → `webhook_verifie:true`.
5. Événement `checkout.session.completed` **signé** (HMAC `t.payload`) → `POST /api/stripe/webhook` :
   - signature **valide → 200**, paiement passé **`pending` → `complete`** ;
   - signature **forgée → 400**, **absente → 400** (le trou du mock S131 ne revient pas).

## Honnêteté technique — ce qui reste pour le vrai LIVE externe

- **Emails** : passer Mailpit → vrai SMTP (Gmail mdp d'app / Postmark / SES), **mdp au coffre**, SPF/DKIM/DMARC pour la délivrabilité. Cron quotidien des relances → **brique `horloge` (S29)**.
- **Comptes** : le lien d'action pointe vers `host.docker.internal:8081` (Keycloak interne) — OK en dev seulement ; en prod il faut un **Keycloak public**. Manque le « le client **se connecte effectivement** » de bout en bout.
- **Stripe** : checkout 100 % live contre l'API Stripe ; le **webhook** a été prouvé contre le conteneur live avec un événement self-signé (Stripe CLI absent). Pour le vrai bout-en-bout Stripe-originé : `stripe login` + `stripe listen` (vrai `whsec_`) ou endpoint dashboard, puis paiement carte `4242 4242 4242 4242` sur la page checkout.
