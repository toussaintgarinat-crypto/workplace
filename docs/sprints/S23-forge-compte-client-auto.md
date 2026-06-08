# Sprint S23 — Compte client auto à la livraison

> **Statut** : ✅ **CODE LIVRÉ + PROUVÉ OFFLINE** (2026-06-08). Chemin LIVE (Keycloak réel
> avec `manage-users` + SMTP du realm + connexion effective) à rejouer — documenté ci-dessous.

## Objectif

À la livraison d'une app *hébergée*, **créer automatiquement le compte d'accès du client**
(Oria/Keycloak, realm `oria`) à partir de son email, **lui envoyer ses accès** et le
**rattacher à son espace** de messagerie. Avant ce sprint, la livraison provisionnait
l'espace Oria sous le **compte de service** — le client n'avait ni compte ni identifiants.

## Décisions actées

- **Mot de passe = lien Keycloak** (`execute-actions-email` → `UPDATE_PASSWORD` + `VERIFY_EMAIL`),
  pas de mot de passe en clair dans l'email. **Aucun secret ne circule.** (Option B « recommandée »
  de la note de prépa ; l'option A « mot de passe généré + envoyé en clair » est écartée.)
- **Realm cible = `oria`** (SSO central), cohérent avec `oria_provisioning.py` qui crée déjà
  l'espace sous ce realm. (Le realm du bundle `client-<slug>` reste une évolution liée à la
  souveraineté — cf. `sprint-pont-consenti-crm`.)
- **Best-effort, jamais bloquant** : si l'onboarding échoue (Keycloak/SMTP injoignable), l'app
  se livre quand même ; un statut détaillé est journalisé sur l'app.

## Ce qui a été livré (code)

### Nouveau module `briques/generateur/client_provisioning.py`
`creer_compte_client(email, nom_contact, world_id, nom_entreprise) -> statut` :
1. **Crée ou retrouve** l'utilisateur Keycloak (realm `oria`) — **idempotent** : recherche
   par email (`GET …/users?email=&exact=true`) d'abord, gère le 409 (course).
2. **Déclenche l'email d'accès** via Keycloak (`PUT …/users/{id}/execute-actions-email`
   `["UPDATE_PASSWORD","VERIFY_EMAIL"]`, `client_id=oria-app`, `redirect_uri=ORIA_URL_PUBLIQUE`,
   `lifespan=7 j`). C'est **Keycloak** qui envoie → aucun code email dans le noyau.
3. **Rattache** le client à son world (`POST /api/worlds/{id}/rejoindre`, `user_id=sub`),
   cohérent avec l'auto-provisioning Oria au 1ᵉʳ login (id = `sub`). L'invitation Matrix se
   fait au login (le membre est pré-enregistré ici).
   Réutilise l'auth de service (`oria_provisioning._token`, client `workplace-provisioner`).

### Câblage de bout en bout
- **Générateur** (`main.py`) : `DemandeGeneration` gagne `email_client` + `contact_client` ;
  `_generer_en_background` appelle `client_provisioning` **après** le provisioning de l'espace
  (besoin du `world_id`) ; statut stocké en base (**nouvelle colonne `client_onboarding`**,
  migration `ALTER TABLE` douce) et exposé par `GET /apps/{id}`.
- **Noyau** (`core/orchestrateur.py`) : `creer_livraison` + `executer_pipeline` +
  `_etape_generation` transportent `email_client`/`contact_client` jusqu'au `/generer`
  (**nouvelles colonnes `email_client`/`contact_client`** sur `livraisons`, migration douce).
- **Noyau** (`core/main.py`) : `POST /usine/livrer` accepte `email_client` + `contact_client`
  (Form) ; le **formulaire du dashboard** gagne les deux champs (l'email reste optionnel —
  vide ⇒ comportement actuel inchangé).

## Preuve offline (5/5) — `briques/generateur/test_client_provisioning.py`
Keycloak admin + Oria simulés par un `httpx.MockTransport` :
1. **nouveau client** → compte créé + email d'accès envoyé + rattaché à l'espace ;
2. **client déjà présent** → idempotent (aucun `POST /users`), email renvoyé ;
3. **email absent/invalide** → onboarding ignoré, **aucun appel réseau** ;
4. **Keycloak injoignable** → échec best-effort, **aucune exception** levée ;
5. **SMTP KO** (execute-actions-email 500) → compte quand même créé, `email_envoye=False`,
   rattachement quand même tenté.

`python3 -m py_compile` OK sur les 5 fichiers touchés. Aucune nouvelle dépendance (httpx déjà présent).

## Reste à prouver LIVE (honnêteté technique)
- [ ] **Droits Keycloak** : donner au compte de service `workplace-provisioner` le rôle
      `realm-management:manage-users` sur le realm `oria` (sinon `GET/POST …/users` → 403).
- [ ] **SMTP du realm `oria`** configuré (Mailpit en dev) pour que `execute-actions-email`
      parte réellement — même classe de dépendance que le LIVE de S22.
- [ ] **Bout-en-bout** : une livraison avec un email client → compte `oria` créé, le client
      **reçoit** le lien, **définit son mot de passe** et **se connecte** à Oria/son espace.

## Notes d'honnêteté technique
- **« Lien envoyé » ≠ « client connecté ».** On prouve ici la **logique** (création idempotente,
  déclenchement de l'email, rattachement, best-effort) sans dépendre d'un Keycloak/SMTP réel.
  La délivrabilité et la connexion effective dépendent des droits + du SMTP du realm (LIVE).
- **Pas de secret en clair** : choix du lien Keycloak plutôt que d'un mot de passe transmis —
  posture cohérente avec le durcissement des secrets (cf. `sprint-durcissement-secrets-oria-forge`).
- **Rattachement avant 1ᵉʳ login** : `/rejoindre` pré-enregistre l'appartenance ; l'identité
  Matrix (et donc l'invitation aux salons) est provisionnée au 1ᵉʳ `/api/auth/me`, inchangé
  depuis S3/S14. Si l'id Oria ≠ `sub`, la jonction se refait de toute façon au login via le widget.
- **Dette** : réutilise l'identité de service unique (Workplace mono-propriétaire) ; le choix
  realm central vs realm du bundle au décrochage est laissé à `sprint-pont-consenti-crm`.

> Voir aussi `WORKPLACE.md` (entrée 2026-06-08), `sprint-compte-client-auto` (mémoire),
> et le module `briques/generateur/client_provisioning.py`.
