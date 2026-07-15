# Épopée S171→S173 — identité multi-utilisateur du Cœur

But : donner à Marina (et à d'autres personnes futures) une vraie identité distincte de
l'utilisateur principal, pour que les briques puissent enfin dire « qui » fait quoi —
préalable bloquant pour le roadmap agenda S171→S177 (rappels par personne, présence,
journal d'activité), voir [[roadmap-s171-s177-agenda-best-in-class]].

Statut : **PLANIFIÉ, lancement immédiat** (décidé avec l'utilisateur 2026-07-15). Chaque
sous-sprint sera brainstormé en détail à son lancement, comme les autres épopées du
projet (Organisme vivant S63→S71, refactor clarté S114→S124, etc.) — ce document fixe le
découpage et l'ordre, pas les specs fines.

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

## S171 — Login Keycloak réel pour le dashboard du Cœur

- Poser une vraie session utilisateur sur `core/routers/dashboard.py` (aujourd'hui
  accès direct) : écran de connexion, cookie/JWT de session, déconnexion.
- Choix du realm (`oria` vide vs `forge` qui a déjà `calendar-app` prêt) et de son
  périmètre (uniquement le dashboard humain, ou aussi les endpoints REST du Cœur) à
  trancher au brainstorm dédié.
- Contrainte forte : ne pas casser les chemins automatisés existants qui tournent en
  mono-user pinné (Telegram, proactif, outils LLM S2S) — l'assistant garde son identité
  de service, seul l'accès humain au dashboard change.

## S172 — Provisioning du second compte (Marina)

- Créer le compte Keycloak de Marina + flux d'invitation, en réutilisant le gabarit
  `client_provisioning.py` (S23) adapté à un usage interne/foyer plutôt que B2B.
- Modéliser le lien « plusieurs personnes, mêmes données partagées » (pas de vrai
  multi-tenant façon Forge/org_id — Marina doit voir le même agenda, pas un agenda
  séparé) : concept à concevoir de zéro, aucun précédent dans le repo.

## S173 — Routage S2S par utilisateur réel

- Remplacer le pinning en dur (`AGENDA_USER_ID="perso"`, `ADMIN_COMPTE_ID="admin"`) par
  l'identité de session captée en S171/S172, propagée du Cœur vers les briques.
- Périmètre S173 : agenda en priorité (bloque le roadmap S171→S177 agenda) ; restaurant
  si le temps le permet, sinon reporté à un sprint dédié plus tard.

## Hors périmètre / à clarifier au lancement

- Authentifier chaque brique une par une au-delà d'agenda/restaurant : hors scope de
  cette épopée, à traiter brique par brique si le besoin se confirme.
- Migrer l'auth locale du restaurant vers Keycloak : hors scope sauf si S173 le rend
  trivial une fois le routage S2S en place — à trancher à l'ouverture de S173.
