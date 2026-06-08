# Sprint S21 — Stripe réel (encaissement en ligne véritable)

> **But du sprint** : remplacer le **Stripe mock** de Forge (session factice, webhook non
> vérifié) par une intégration **réelle** : SDK Stripe officiel, **clé secrète au coffre
> chiffré**, **webhook à signature vérifiée**. C'est le prolongement direct de S20
> (`facturation` + `crm`) : la chaîne commerciale `prospect → devis → facture` se boucle
> enfin sur un **paiement en ligne réel**.

- **Sprint** : S21
- **Pré-requis** : **S20** (facturation prouvée — c'est elle qui produit l'euro à encaisser)
- **Déclencheur** : encaissement réel imminent (un client doit pouvoir payer en ligne).
- **Statut** : **réalisé côté code + prouvé offline (2026-06-08)**. Le SDK réel, le coffre
  chiffré et la **vérification de signature webhook** sont implémentés et **prouvés sans
  Stripe** (test de signature, round-trip de chiffrement, dégradation). L'**appel live**
  (création d'une vraie session de paiement contre l'API Stripe) reste à rejouer avec une
  **clé de test `sk_test_…`** — voir « Réalisé » et « Notes d'honnêteté ».

---

## 0. Constat de départ (vérifié dans le code)

- `forge/core/app/routers/stripe.py` est un **mock fidèle au Bun** : `POST /stripe/checkout`
  fabrique un `sessionId` factice (`cs_<ts>_<rand>`), trace un paiement `pending`, et renvoie
  une fausse `checkoutUrl`. Le `POST /stripe/webhook` passe le paiement à `complete` **sans
  aucune vérification de signature** — n'importe qui peut le déclencher.
- **Aucun SDK Stripe** dans `requirements.txt`, **aucune clé** dans l'environnement.
- Le **coffre chiffré existe déjà** : `app/crypto.py` (AES-256-GCM, compatible Bun) +
  `ProviderApiKeys` (clés providers chiffrées en base) + `app/keystore.py` (résolution
  base → env, cache TTL). On le **réutilise** pour la clé Stripe : aucune nouvelle brique de
  secret à inventer.
- Le motif adaptateur S17/S20 (`briques/forge/main.py`) est en place : routes FR
  authentifiées par token de service, dégradation propre. On y ajoute une capacité `paiement`.

---

## Chantier 1 — SDK Stripe réel + clé au coffre

> Remplacer la session factice par une **vraie session Checkout** Stripe.

### Conception
- **Dépendance** : `stripe` (SDK officiel) ajouté à `requirements.txt`.
- **Résolution de la clé** (coffre → env, jamais en clair dans le code) :
  - clé secrète stockée **chiffrée** en base (`ProviderApiKeys`, provider `stripe`) via
    `crypto.encrypt`, **ou** repli sur l'env `STRIPE_SECRET_KEY` (parité keystore) ;
  - un helper `resolve_stripe_key()` déchiffre/lit, **masque** la clé dans les logs.
- **Checkout réel** : si une clé est résolue → `stripe.checkout.Session.create(...)`
  (mode `subscription`, `success_url`/`cancel_url` config) → on stocke le **vrai**
  `session.id` (`StripePayments`) et on renvoie la **vraie** `session.url`.
- **Dégradation propre** : **aucune clé** configurée → réponse claire `mode: "mock"`
  (comportement historique conservé, jamais de crash) plutôt qu'une erreur opaque.

### Critères d'acceptation
- [x] La clé secrète n'apparaît **jamais en clair** (chiffrée en base ou en env ; masquée en log).
- [x] Clé présente → le checkout appelle le **vrai** SDK (params corrects : plan→prix, devise, URLs).
- [x] Aucune clé → dégradation explicite (`mode: mock`), pas de stacktrace.
- [ ] **(live)** Une vraie session Checkout est créée contre Stripe (test mode) et renvoie une URL payable — **à rejouer avec `sk_test_`**.

---

## Chantier 2 — Webhook à signature vérifiée

> Le point de sécurité du sprint : **personne** ne doit pouvoir marquer un paiement « payé ».

### Conception
- Le webhook devient **public** (Stripe n'envoie pas de token Keycloak) mais **vérifié** :
  `stripe.Webhook.construct_event(payload_brut, header Stripe-Signature, STRIPE_WEBHOOK_SECRET)`.
- Signature invalide / absente / corps trafiqué → **400** (rejet), aucun effet de bord.
- Secret de webhook **absent** → le webhook **refuse** par défaut (pas de bascule silencieuse
  vers le mode non vérifié en présence d'une vraie clé Stripe).
- Sur `checkout.session.completed` vérifié → on passe le `StripePayments` à `complete`
  (idempotent), inchangé fonctionnellement par rapport au mock.

### Critères d'acceptation
- [x] Signature **valide** (secret connu) → événement accepté, paiement passé à `complete`.
- [x] Signature **falsifiée** ou **absente** → **400**, **aucun** changement en base.
- [x] Corps **trafiqué** après signature → rejet (la signature ne matche plus).
- [x] Secret webhook absent (avec clé Stripe présente) → webhook refuse proprement.

---

## Chantier 3 — Adaptateur + assistant (contrat « paiement »)

> Exposer l'encaissement en langage Workplace, **sans** jamais faire transiter la clé par le LLM.

### Conception
- `briques/forge/main.py` : capacité `paiement` + routes FR :
  - `GET /paiement/etat` — Stripe est-il **réellement** configuré (clé live/test) ou en mock ? (lecture)
  - `GET /paiement/plans`, `GET /paiement/abonnement`, `GET /paiement/paiements` (lecture)
  - `POST /paiement/lien` — créer un **lien de paiement** réel pour un plan (action).
- `core/outils.py` : `forge_paiement_etat` (lecture libre), `forge_paiement_lien` (action confirmée).
- **Décision de sécurité** : la **configuration de la clé** ne passe **pas** par un outil
  assistant (un secret ne doit pas transiter dans une conversation LLM). Elle se fait par
  `.env`/coffre, hors assistant. L'assistant ne fait que **constater l'état** et **créer un lien**.

### Critères d'acceptation
- [x] `forge_paiement_etat` dit honnêtement « Stripe réel configuré » vs « mode mock ».
- [x] `forge_paiement_lien` (confirmé) renvoie un lien de paiement (réel si clé, sinon mock clair).
- [x] Aucun outil ne lit/écrit la clé secrète.
- [x] Dégradation propre si Forge/clé absents (message clair, jamais de stacktrace).

---

## Séquencement & dépendances

```
Chantier 1 (SDK réel + clé coffre)
   └─► Chantier 2 (webhook signé)        ← cœur sécurité
          └─► Chantier 3 (adaptateur + assistant)
```

**Ordre** : `1 → 2 → 3`. Et **S21 après S20**.

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S21-1 | `stripe` dans requirements + settings (clé, webhook secret, URLs) | 1 | S |
| S21-2 | `resolve_stripe_key()` (coffre chiffré → env, masquage) | 1 | S |
| S21-3 | Checkout réel via SDK + dégradation mock si pas de clé | 1 | M |
| S21-4 | Webhook public à signature vérifiée (`construct_event`) | 2 | M |
| S21-5 | Adaptateur capacité `paiement` (état/plans/abonnement/paiements/lien) | 3 | M |
| S21-6 | Outils assistant `forge_paiement_etat` / `forge_paiement_lien` | 3 | S |
| S21-7 | Preuve offline (signature, chiffrement, dégradation) + maj journal | — | S |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j.

---

## Métriques de succès du sprint

- **Sécurité réelle** : un webhook non signé ne peut **plus** marquer un paiement payé.
- **Secret protégé** : la clé Stripe est chiffrée au repos, jamais en clair, jamais dans le LLM.
- **Dégradation honnête** : sans clé, le système le **dit** (`mode: mock`) au lieu de simuler un encaissement.

## Hors-scope

- Gestion d'abonnements avancée (proration, upgrades/downgrades, portail client Stripe).
- Facturation Stripe Invoicing (distincte de la `facturation` interne S20).
- Multi-comptes Stripe / multi-devises au-delà de l'EUR par défaut.

---

## Réalisé (2026-06-08)

### Code livré
- **Core** : `requirements.txt` (+`stripe==11.1.0`) ; `config.py` (4 settings Stripe) ;
  `routers/api_keys.py` (provider `stripe` ajouté → chemin coffre réel) ;
  `routers/stripe.py` **réécrit** : `resolve_stripe_key()` (coffre chiffré → env, masquée),
  `GET /stripe/etat` (réel-vs-mock, sans jamais révéler la clé), `POST /stripe/checkout`
  réel (SDK, abonnement mensuel, prix inline EUR) avec **dégradation `mock`** sans clé,
  `POST /stripe/webhook` **public à signature vérifiée**.
- **Adaptateur** (`briques/forge/main.py`) : capacité `paiement` + routes FR
  `GET /paiement/etat|plans|abonnement|paiements`, `POST /paiement/lien`.
- **Assistant** (`core/outils.py`) : `forge_paiement_etat` (lecture libre),
  `forge_paiement_lien` (action confirmée). **La clé ne transite jamais par l'assistant.**

### Preuve offline (9/9, venv `stripe==11.1.0`, sans réseau — `/tmp/s21_preuve.py`)
- **Webhook signé (Chantier 2)** : signature valide → événement accepté ;
  signature falsifiée (mauvais secret), signature absente, **corps trafiqué après coup**
  → `SignatureVerificationError` (rejet). C'est le **vrai risque** du sprint, prouvé.
- **Coffre chiffré (Chantier 1)** : `encrypt`→`decrypt` round-trip exact ; clé chiffrée
  ≠ clair ; IV aléatoire (2 chiffrements diffèrent) ; masquage log (`sk_t••••••••••••VuTs`).
- **Statique** : 5 fichiers compilent ; symboles SDK utilisés tous présents en 11.1.0.

### Preuve d'intégration (routers RÉELS + Postgres RÉEL)
Le **vrai router stripe** monté dans une app FastAPI contre un Postgres réel (auth Keycloak
remplacée par override) : `GET /stripe/etat` → `mode mock` (sans clé) ; `POST /stripe/webhook`
**sans secret → 503**, **signature invalide → 400**, **signature valide → 200 `received`**.
La vérification de signature passe donc par l'endpoint réel, pas seulement en unité.

### Reste à prouver LIVE (honnêteté)
- [ ] Création d'une **vraie** session Checkout contre l'API Stripe (mode test) →
      nécessite une clé `sk_test_…`. Tout ce qui ne demande pas le réseau est prouvé ;
      cet appel-là est **écrit et compilé** mais **pas rejoué** faute de clé.

> Voir aussi le journal `WORKPLACE.md` (entrée 2026-06-08) et le **guide de connexion
> `GUIDE-stripe.md`** (clés, coffre, `stripe listen`, test carte 4242, passage live).

## Notes d'honnêteté technique

- **« Code réel » ≠ « encaissement prouvé live ».** Sans clé `sk_test_`, je ne peux pas créer
  une vraie session Checkout contre Stripe. J'ai donc **prouvé tout le provable hors-ligne**
  (le plus important — la **vérification de signature webhook** — est 100 % testable sans réseau :
  HMAC-SHA256 sur secret connu), et **laissé l'appel live explicitement à rejouer** dès qu'une
  clé de test est fournie. Pas de faux « ça marche ».
- **Le webhook est la surface dangereuse**, pas le checkout : un checkout factice ne coûte rien,
  mais un webhook non vérifié laisse n'importe qui marquer une facture « payée ». C'est pourquoi
  le chantier 2 est traité comme le cœur du sprint et prouvé en priorité.
- **Identité de service (dette S20 héritée)** : `StripePayments` scope par `user_id` ; via le
  token de service unique de l'adaptateur, tout vit sous l'identité Workplace mono-propriétaire.
  Cohérent avec le modèle actuel (un Jarvis = une entreprise) ; à propager si multi-utilisateur réel.
