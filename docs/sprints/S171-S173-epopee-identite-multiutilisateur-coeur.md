# Épopée S171→S173 — identité multi-utilisateur du Cœur

But : donner à Marina (et à d'autres personnes futures) une vraie identité distincte de
l'utilisateur principal, pour que les briques puissent enfin dire « qui » fait quoi —
préalable bloquant pour le roadmap agenda S174→S180 (rappels par personne, présence,
journal d'activité), voir [[roadmap-s174-s180-agenda-best-in-class]].

Statut : **EN COURS** (décidé avec l'utilisateur 2026-07-15). S171 CODE-COMPLET le même
jour (PR #3, branche `worktree-s171-login-keycloak-coeur`, non mergée). Chaque sous-sprint
est brainstormé en détail à son lancement, comme les autres épopées du projet (Organisme
vivant S63→S71, refactor clarté S114→S124, etc.) — ce document fixe le découpage et
l'ordre, pas les specs fines. Numérotation : cette épopée occupe **S171→S173** en tête de
séquence (contigu, pas de collision), le roadmap agenda démarre juste après à **S174**.

État constaté au moment du cadrage (à revérifier au lancement de chaque sous-sprint) :

- Le Cœur (`core/`) n'a **aucune authentification utilisateur** aujourd'hui :
  `core/main.py` ne pose aucun middleware d'auth, `core/routers/dashboard.py` est monté
  sans dépendance de session, `core/contexte_tenant.py` capte des en-têtes
  `X-User-Id`/`X-Org-ID` s'ils sont présents mais ne les vérifie jamais (défaut
  `"perso"`/`"defaut"` sinon). Accès direct, sans login.
- Le seul vrai login Keycloak visible dans le dashboard est celui de **Forge**, chargé en
  iframe et géré entièrement par Forge/Oria (realm `oria`) — le Cœur ne participe pas à
  cette session.
- Deux realms Keycloak existent en config statique, tous deux vides (`users: null`) :
  `oria-stack/oria/keycloak/oria-realm.json` (realm `oria`, clients `oria-app` +
  `forge-service`) et `oria-stack/infra/keycloak/realms/forge-realm.json` (realm `forge`,
  rôles `admin`/`member`, 7 clients dont **`calendar-app`** — client OIDC PKCE déjà
  préparé pour l'agenda, `redirectUris: localhost:8400`, jamais utilisé). Seul
  `forge-realm.json` est importé automatiquement par
  `oria-stack/infra/keycloak/docker-compose.yml` — à vérifier/synchroniser au lancement
  de S171.
- Le pinning mono-user n'est pas propre à l'agenda : le restaurant a le même schéma
  (`X-Compte-Id` pinné sur `ADMIN_COMPTE_ID="admin"` côté Cœur,
  `core/outils_communs.py`), mais avec son **propre système d'auth local** (compte/mdp/
  session en base restaurant, pas Keycloak — `briques/restaurant/main.py`).
- Un flux de provisioning Keycloak existe déjà, côté Générateur (S23, onboarding client
  B2B) : `briques/generateur/client_provisioning.py` crée un utilisateur via l'API admin
  Keycloak du realm `oria` puis déclenche l'email natif Keycloak
  `execute-actions-email` (`UPDATE_PASSWORD`+`VERIFY_EMAIL`), sans jamais manipuler de
  mot de passe en clair. Bon gabarit à réutiliser pour S172.
- Aucun mécanisme de « foyer/compte partagé » (plusieurs personnes, un tenant commun)
  n'existe dans le repo — à concevoir de zéro.

## Ordre et dépendances

```
S171 (login Keycloak réel pour le dashboard du Cœur)
   └─> S172 (provisioning du second compte — Marina)
        └─> S173 (routage S2S par utilisateur réel, agenda en priorité)
```

## S171 — Login Keycloak réel pour le dashboard du Cœur — ✅ CODE-COMPLET (PR #3)

- Vraie session utilisateur sur `core/routers/dashboard.py` (était en accès direct) :
  flux OAuth Authorization Code + PKCE, cookie de session chiffré AES-GCM, déconnexion.
- Realm retenu : `forge` (pas `oria`, resté vide), client `assistant-app` — pas
  `calendar-app` qui sert uniquement la page d'invitation agenda. `redirectUris`
  obsolètes (`localhost:8300`) corrigées vers le vrai port du Cœur (`localhost:5100`).
- Portée : uniquement `dashboard.router`. Chemins automatisés (Telegram, proactif,
  outils LLM S2S) inchangés — `core/contexte_tenant.py` (S121) assurait déjà la
  propagation d'identité par requête, seule l'authentification manquait.
- Livré : `core/auth.py`, `core/routers/auth.py`, 6 tâches TDD + revue finale de branche
  (1 fix Important : `/auth/callback` renvoyait un 500 nu au lieu du repli 303 attendu).
  Suite 426/426. Spec : `docs/superpowers/specs/2026-07-15-s171-login-keycloak-coeur-design.md`.
  Plan : `docs/superpowers/plans/2026-07-15-s171-login-keycloak-coeur.md`.
  RESTE : vérification manuelle LIVE (Keycloak + Cœur en local), merge de la PR.

## S172 — Provisioning du second compte (Marina)

- Créer le compte Keycloak de Marina + flux d'invitation, en réutilisant le gabarit
  `client_provisioning.py` (S23) adapté à un usage interne/foyer plutôt que B2B.
- Modéliser le lien « plusieurs personnes, mêmes données partagées » (pas de vrai
  multi-tenant façon Forge/org_id — Marina doit voir le même agenda, pas un agenda
  séparé) : concept à concevoir de zéro, aucun précédent dans le repo.

## S173 — Routage S2S par utilisateur réel

- Remplacer le pinning en dur (`AGENDA_USER_ID="perso"`, `ADMIN_COMPTE_ID="admin"`) par
  l'identité de session captée en S171/S172, propagée du Cœur vers les briques.
- Périmètre S173 : agenda en priorité (bloque le roadmap S174→S180 agenda) ; restaurant
  si le temps le permet, sinon reporté à un sprint dédié plus tard.

## Hors périmètre / à clarifier au lancement

- Authentifier chaque brique une par une au-delà d'agenda/restaurant : hors scope de
  cette épopée, à traiter brique par brique si le besoin se confirme.
- Migrer l'auth locale du restaurant vers Keycloak : hors scope sauf si S173 le rend
  trivial une fois le routage S2S en place — à trancher à l'ouverture de S173.
