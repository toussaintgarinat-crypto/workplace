# Sprint S22 — Emails & relances automatiques (recouvrement des impayés)

> **But du sprint** : rendre l'**email transactionnel réel** sur le socle existant
> (`app/email.py`, déjà câblé pour un seul email) et bâtir dessus le **recouvrement
> automatique des factures impayées** : relances **J+7 / J+15 / J+30**, anti-doublon,
> journalisées. C'est la suite directe de S20/S21 — la facture émise (S20) qui n'est pas
> payée (S21) **se relance toute seule** : le chemin le plus court vers l'euro **déjà dû**.

- **Sprint** : S22
- **Pré-requis** : **S20** (`facturation` — les factures à relancer) ; complète **S21** (encaissement).
- **Déclencheur** : facturation en usage réel (premiers clients facturés, premiers impayés).
- **Statut** : **réalisé côté code + prouvé offline (2026-06-08)**. Email réel prouvé contre un
  **serveur SMTP local** (envoi reçu et vérifié, sans identifiants externes) ; cadence des
  relances + anti-doublon prouvés. L'envoi via **SMTP réel** (Gmail/transactionnel) reste à
  rejouer avec des identifiants — voir « Réalisé » et `GUIDE-emails.md`.

---

## 0. Constat de départ (vérifié dans le code)

- **`app/email.py` existe** (S130) : `_send_sync` (stdlib `smtplib`, `asyncio.to_thread`) +
  un seul template (`send_venture_deletion_code`). Config SMTP déjà en place
  (`config.py` : `SMTP_HOST/PORT/SECURE/USER/PASS/FROM`). Socle réel, **sous-exploité**.
- **`SMTP_PASS` est en clair dans l'env** → on le déplace au **coffre chiffré**
  (`ProviderApiKeys`/`crypto.py`, comme la clé Stripe en S21), repli env conservé.
- **`FacturesDocs`** porte tout ce qu'il faut pour relancer : `client_email`, `client_nom`,
  `numero`, `total_ttc`, `statut` (`envoyée` = impayé en attente), `date_echeance`.
- **Motif anti-doublon connu** : `core/proactif.py` journalise les rappels dans un SQLite
  side-car avec une **clé d'unicité** (un rappel par clé). On réplique : une relance par
  `(facture, niveau)`.

---

## Chantier 1 — Email réel (socle généralisé, mot de passe au coffre)

### Conception
- `config.py` : `resolve_smtp_password()` lit le mot de passe **chiffré** (`ProviderApiKeys`
  provider `smtp`) → repli env `SMTP_PASS`. Ajout `SMTP_STARTTLS` (défaut `True`) pour les
  relais internes/dev sans STARTTLS (et pour prouver l'envoi en local).
- `email.py` : `send(to, subject, html)` générique + templates :
  - **facture émise** (envoi de la facture au client) ;
  - **relance impayée** à 3 niveaux (J+7 courtois, J+15 ferme, J+30 mise en demeure douce).
- Le mot de passe n'apparaît **jamais en clair** (coffre, masqué en log).

### Critères d'acceptation
- [x] Un email réel part et **arrive** (prouvé contre un SMTP local, sans identifiants externes).
- [x] Mot de passe SMTP résolu depuis le coffre → env, jamais loggé en clair.
- [x] Templates rendus corrects (destinataire, sujet, montant, numéro, niveau de relance).

---

## Chantier 2 — Moteur de relances impayées (J+7 / J+15 / J+30)

### Conception
- `app/relances.py` : `scan_impayes()` sélectionne les factures `envoyée` dont la
  `date_echeance` est dépassée de ≥ 7/15/30 jours **et** qui ont un `client_email`.
- Niveau de relance déduit du retard ; **anti-doublon** par `(facture_id, niveau)` dans un
  **journal SQLite** side-car (motif `proactif.py`) → une relance par niveau et par facture.
- `executer()` envoie les relances dues et journalise ; `apercu()` = **dry-run** (qui serait
  relancé, à quel niveau) sans rien envoyer.
- Router `routers/relances.py` : `GET /relances/impayes/apercu`, `POST /relances/impayes/executer`,
  `GET /relances/journal`. Monté `/api` (motif des autres routers).

### Critères d'acceptation
- [x] Cadence correcte : une facture échue depuis 8 j → niveau J+7 ; 20 j → J+15 ; 40 j → J+30.
- [x] **Anti-doublon** : ré-exécuter ne renvoie pas une relance déjà envoyée pour ce niveau.
- [x] `apercu` n'envoie rien (dry-run) ; `executer` envoie et journalise.
- [x] Facture sans email → ignorée proprement (signalée, pas d'erreur).

---

## Chantier 3 — Adaptateur + assistant (contrat « relances »)

### Conception
- `briques/forge/main.py` : capacité `relances` + routes FR :
  - `GET /relances/apercu` — qui serait relancé (lecture, dry-run) ;
  - `POST /relances/executer` — lancer les relances dues (action) ;
  - `GET /relances/journal` — historique des relances (lecture) ;
  - `POST /facturation/{id}/envoyer` — **envoyer une facture par email** au client (action ;
    passe `brouillon`→`envoyée` et déclenche l'horloge des relances).
- `core/outils.py` : `forge_relances_apercu` (lecture), `forge_relances_envoyer` (action),
  `forge_facture_envoyer` (action).

### Critères d'acceptation
- [x] `forge_relances_apercu` liste les relances à venir sans rien envoyer.
- [x] `forge_relances_envoyer` (confirmé) envoie et renvoie un récap (nb, montants).
- [x] `forge_facture_envoyer` (confirmé) envoie la facture et la passe `envoyée`.
- [x] Dégradation propre si SMTP/clé/Forge absents (message clair, jamais de stacktrace).

---

## Séquencement & dépendances

```
Chantier 1 (email réel + coffre)
   └─► Chantier 2 (moteur relances impayées)   ← cœur valeur (euro déjà dû)
          └─► Chantier 3 (adaptateur + assistant)
```

**Ordre** : `1 → 2 → 3`. Et **S22 après S20**.

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S22-1 | `resolve_smtp_password()` (coffre→env) + `SMTP_STARTTLS` | 1 | S |
| S22-2 | `email.py` : `send()` + templates (facture émise, relance ×3) | 1 | M |
| S22-3 | `relances.py` : scan échus J+7/15/30 + anti-doublon SQLite | 2 | M |
| S22-4 | `routers/relances.py` (apercu/executer/journal) + montage | 2 | M |
| S22-5 | Adaptateur capacité `relances` + envoyer facture par email | 3 | M |
| S22-6 | Outils assistant (apercu/envoyer relances, envoyer facture) | 3 | S |
| S22-7 | Preuve offline (SMTP local + cadence + anti-doublon) + guide + journal | — | S |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j.

---

## Métriques de succès du sprint

- **Recouvrement réel** : une facture échue déclenche une **vraie relance** reçue et journalisée.
- **Pas de spam** : anti-doublon strict (une relance par niveau et par facture).
- **Secret protégé** : mot de passe SMTP chiffré au repos, jamais en clair.

## Hors-scope (→ incréments suivants)

- Relances **prospects** (sans réponse) et **rappels de RDV** par email — moteur réutilisable,
  branchés plus tard (CRM/agenda).
- **Opt-out / désinscription** (obligatoire pour du marketing, pas pour une relance de facture
  due) — à ajouter avec les relances prospects.
- **Planification automatique** (cron) : le moteur est **exécutable à la demande** et via la
  boucle proactive ; le déclencheur périodique autonome est documenté, pas encore activé live.
- Délivrabilité (SPF/DKIM/DMARC) — relève du choix de fournisseur (cf. `GUIDE-emails.md`).

---

## Réalisé (2026-06-08)

### Code livré
- **Core** : `config.py` (`SMTP_STARTTLS`, mdp au coffre) ; `email.py` **généralisé**
  (`resolve_smtp_password()` coffre→env, `send()` générique, templates `facture_emise` +
  `relance` ×3 niveaux) ; `relances.py` (cadence pure `niveau_du`, scan factures `envoyée`
  échues, **anti-doublon SQLite** side-car, `apercu`/`executer`/`journal`) ;
  `routers/relances.py` (`/relances/impayes/apercu|executer`, `/relances/journal`,
  `POST /facturation/{id}/envoyer`) monté `/api` ; provider `smtp` ajouté à `api_keys.py`.
- **Adaptateur** (`briques/forge/main.py`) : capacité `relances` + routes FR
  `/relances/apercu|executer|journal`, `POST /facturation/{id}/envoyer`.
- **Assistant** (`core/outils.py`) : `forge_relances_apercu` (lecture), `forge_relances_envoyer`
  + `forge_facture_envoyer` (actions confirmées).

### Preuve offline (15/15, venv, sans identifiants externes — `/tmp/s22_preuve.py`)
- **Envoi SMTP RÉEL** : `email.py._send_sync` contre un serveur **aiosmtpd local** →
  message réellement transmis, destinataire/sujet/numéro/montant vérifiés dans le contenu.
- **Cadence** : retard 6 j → aucune ; 8 → J+7 ; 20 → J+15 ; 40 → J+30 ; templates distincts.
- **apercu/executer/anti-doublon** (docs + SMTP simulés) : aperçu = 3 dues, dry-run **n'envoie
  rien**, facture sans email **ignorée signalée** ; executer → 3 envoyées (niveaux 7/15/30) ;
  **ré-exécuter → 0** (anti-doublon) ; journal = 3 tracées.
- **Statique** : 8 fichiers compilent.

### Preuve d'intégration (17/17, routers RÉELS + Postgres RÉEL + Mailpit RÉEL)
Les **vrais routers** (facturation + relances + stripe) montés dans une app FastAPI contre un
**Postgres réel** (schéma `init_db`, 87 tables) et **Mailpit réel** ; seule l'auth Keycloak est
remplacée (override de dépendance). Flux prouvé bout-en-bout :
- créer facture (TTC 1440 calculé en base) → **envoyer par email** (statut `envoyée`, email
  *« Votre facture FACT-2026-0001 »* **reçu dans Mailpit**) ;
- rendre la facture échue J+10 → `apercu` la voit au **niveau J+7**, **dry-run n'envoie rien** ;
- `executer` → relance *« Rappel — facture FACT-2026-0001 »* **reçue dans Mailpit**, journalisée ;
  **ré-exécuter → 0 (anti-doublon)** ; journal = 1.
- Stripe (même run) : `/stripe/etat`→mock ; webhook **sans secret→503**, **sig invalide→400**,
  **sig valide→200** — via l'endpoint réel.

### Reste à prouver LIVE (honnêteté)
- [ ] Chemin d'auth **Keycloak réel** (ici remplacé par un override) — couvert par la stack complète.
- [ ] Envoi vers un **vrai destinataire** (Gmail/transactionnel) + délivrabilité (SPF/DKIM) —
      nécessite des identifiants SMTP. Chemin documenté dans `GUIDE-emails.md` (Mailpit en dev,
      puis SMTP réel ; mot de passe au coffre).
- [ ] **Planification périodique** : le moteur est exécutable à la demande ; le cron quotidien
      est documenté (anti-doublon le rend sûr), pas encore câblé dans la boucle proactive.

> Voir aussi `WORKPLACE.md` (entrée 2026-06-08) et le **guide `GUIDE-emails.md`**.

## Notes d'honnêteté technique

- **« Email reçu en local » ≠ « délivré chez un vrai destinataire ».** J'ai prouvé le chemin
  SMTP **pour de vrai** (serveur local, message réellement transmis et inspecté), ce qui valide
  le code d'envoi sans dépendre d'un compte externe. La **délivrabilité réelle** (Gmail/transac,
  SPF/DKIM, anti-spam) dépend des identifiants et du domaine — à rejouer via `GUIDE-emails.md`.
- **Anti-doublon = la vraie exigence.** Un moteur de relances qui re-spamme à chaque exécution
  est pire que pas de moteur. L'unicité `(facture, niveau)` est traitée comme le cœur du chantier 2.
- **Pas de nouvelle table dans le schéma partagé** : le journal anti-doublon est un SQLite
  side-car (motif `proactif.py`) → aucune migration risquée du schéma Postgres partagé.
- **Identité de service (dette S20 héritée)** : factures scopées par `user_id`, une seule
  identité de service traverse l'adaptateur (Workplace mono-propriétaire). Cohérent ; à propager
  si multi-utilisateur réel.
