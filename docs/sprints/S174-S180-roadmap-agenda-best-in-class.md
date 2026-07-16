# Roadmap S174→S180 — brique agenda "best-in-class"

But : égaler/dépasser TimeTree (chat, couleurs, invitations — déjà en base) + combler les
gaps identifiés vs TimeTree/Google Calendar/Cozi/FamilyWall/Fantastical/Bring!, pour que
Marina (et d'autres) utilisent la brique agenda sans revenir sur TimeTree.

Statut : **BLOQUÉ sur préalable** (backlog validé avec l'utilisateur 2026-07-15,
renuméroté le 2026-07-15 pour éviter toute collision avec l'épopée identité — voir
ci-dessous). Au brainstorm de lancement de l'ancien « S171 » (rappels par personne),
constat que ça suppose une vraie notion de personne (nom + canal de notif), inexistante
aujourd'hui — l'agenda est mono-user pinné sur `AGENDA_USER_ID="perso"` (ADR S168,
agenda-surface-de-service) et le Cœur lui-même n'a **aucune authentification
utilisateur** (`core/routers/dashboard.py` tournait en accès direct). Ce préalable est
traité comme une épopée séparée — voir [[epopee-identite-multiutilisateur-coeur]] /
`docs/sprints/S171-S173-epopee-identite-multiutilisateur-coeur.md` — qui occupe les
numéros **S171→S173** (S171 déjà code-complet, PR #3). Ce roadmap agenda **démarre donc
à S174**, immédiatement après l'épopée, séquence unique et contiguë sans double
numérotation. Chaque sprint sera brainstormé en détail (design doc dédié) à son
lancement — ce document fixe le découpage et l'ordre, pas les specs fines.

État constaté au moment du cadrage (à revérifier au lancement de chaque sprint) :
`briques/agenda/backend` a déjà `Calendar`, `Label`, `CalendarMember`, `CalendarInvitation`,
`Event`, `EventParticipant` (pending/accepted/declined/maybe), `EventComment` (chat par
event), `EventAttachment`, SSE temps réel, ponts Google (one-way) + TimeTree (lecture
seule, API officielle fermée depuis 2023-12-22 — voir [[sprint-pont-timetree-lecture]]).
Gaps constatés :
- `Event.rappels` est un champ unique partagé par tous les participants (pas de réglage
  par personne) — point le plus critiqué de TimeTree dans la recherche concurrentielle.
- `EventParticipant.user_id` / `EventComment.user_id` sont de simples chaînes libres, sans
  table de profils pour résoudre un nom affichable ni un canal de notification.

## Ordre et dépendances

```
[préalable : épopée identité multi-utilisateur du Cœur, S171→S173]
   └─> S174 (notifs par personne + présence/chat exposés + journal d'activité)
        └─> S175 (récurrence avancée, indépendant, peut glisser avant/après S174)
        └─> S176 (liste de courses, réutilise notifs S174)
        └─> S177 (sondages de disponibilité, réutilise participants existants)
             └─> S178 (PWA + push web + widgets + digest — canal de notif mobile,
                        bénéficie de tout ce qui précède)
        └─> S179 (géoloc légère + export ICS, indépendants entre eux)
S180 (chiffrement au repos — durcissement sécurité, en dernier, cross-cutting)
```

## S174 — Notifications par personne + présence/chat exposés + journal d'activité — ✅ CODE-COMPLET 2026-07-15 (LIVE différé)

- **Statut** : code-complet, suites vertes (agenda 138 passed, `make test-core` 438
  passed) — voir `briques/agenda/backend/README.md#s174--rappels-par-personne` pour le
  comportement livré. Vérification LIVE différée à la fin du roadmap (fin S180, cf.
  mémoire « LIVE différé jusqu'à fin S180 »).

- Migrer `Event.rappels` (global) → réglage par participant (`EventParticipant.rappels`
  ou table dédiée), sans casser les events existants (migration Alembic + valeur par
  défaut = ancien comportement global). Dépend du provisioning multi-personnes de
  l'épopée identité (S172 de l'épopée) pour savoir à qui envoyer quoi.
- Exposer au dashboard ce qui existe déjà en base mais n'a pas d'UI confirmée : statuts
  de présence (accepted/declined/maybe) et chat (`EventComment`) par événement.
- Journal d'activité : table `event_activity_log` (qui a changé quoi, quand) — posée tôt
  pour tracer les sprints suivants dès leur arrivée. Gabarit possible à reprendre :
  `AuditLogs` de la brique Forge (`briques/forge/forge/core/app/models/generated.py:288`)
  — colonnes user_id/user_nom/action/entite/entite_id/details JSON/created_at.

## S175 — Récurrence avancée ✅ CODE-COMPLET (LIVE différé)

- `Event.recurrence_rule` existe en base mais n'est expansé nulle part (vérifié :
  aucune référence RRULE dans `routers/events.py`). Implémenter l'expansion RRULE réelle
  + gestion des exceptions ("tous les lundis sauf le 25").
- **Livré (2026-07-16)** : occurrences virtuelles au read-time (`services/recurrence.py`
  pur + `services/occurrences.py`), migration 0007 (`exdates`, `recurrence_parent_id`,
  `recurrence_date` + contrainte unique override), câblage des 3 chemins de lecture
  (list_events, agrégation `/service` + correctif N+1 participants, proactif Cœur avec
  clé de dédup par occurrence), API portée `?scope=all|this&occurrence=` sur `/events` et
  `/service`, front (sélecteur récurrence + badge ↻ + dialogue de portée). Design
  `docs/superpowers/specs/2026-07-16-s175-recurrence-rrule-design.md`, plan
  `docs/superpowers/plans/2026-07-16-s175-recurrence-rrule.md`. Suites : agenda 194,
  cœur 439.
- **Fast-follow** : `scope=this_and_following` (scission de série) ; RRULE exotiques
  (`BYSETPOS`, `BYMONTHDAY` multiples) ; smoke `alembic upgrade/downgrade` de 0007 sur
  Postgres avant déploiement (les tests utilisent `create_all`, pas la migration).

## S176 — Liste de courses/tâches partagée (façon Bring!) — ✅ CODE-COMPLET 2026-07-16 (LIVE différé)

- **Statut** : code-complet, suite agenda **243 passed** (+ 1 skip redis), migration `0008`.
  Revue finale (high) : 1 correctif retenu — motif de **stop Code128** tronqué (`233111`→
  `2331112`, barre terminale manquante = symbole inscannable), corrigé + test de largeur
  de modules. 3 findings mineurs laissés en fast-follow (N+1 count `list_lists` ; notif/SSE
  émis sur ajout d'un doublon no-op ; repli d'accents majuscules SQLite dans l'anti-doublon).
  Design `docs/superpowers/specs/2026-07-16-s176-liste-courses-partagee-design.md`, plan
  `docs/superpowers/plans/2026-07-16-s176-liste-courses-cartes-fidelite.md`, ADR push
  événementiel `docs/decisions/2026-07-16-listes-push-evenementiel.md`. Voir
  `briques/agenda/backend/README.md#s176`.
- **Livré** : sous-système **autonome** (6 tables) — `ShoppingList` (`kind`
  courses|taches), `ShoppingListMember`, `ShoppingListInvitation` (partage par lien),
  `ShoppingItem`, `CatalogItem` (catalogue FR emoji ~55 items semé au boot, idempotent),
  `LoyaltyCard`. Cochage **temps réel** via canal SSE dédié `list:{id}:changes`
  (`EventSource` authentifié par token en query — `get_current_user_sse`). Anti-doublon
  façon Bring!. Push par personne **événementiel** best-effort vers `connexion /pousser`
  (`CONNEXION_URL`/`CONNEXION_KEY`, repli honnête). Outils LLM `courses_*` (manifest
  v1.2.0). Front : onglets « Listes » (catalogue tap-to-add par rayon + SSE) et « Cartes »
  (code-barres **Code128/EAN-13** généré par `static/barcode.js` vanilla, sans CDN).
- **Fast-follow** : génération **QR** des cartes (repli numéro en attendant) ; outils LLM
  cartes ; import de recettes ; templates de listes ; quantités structurées ; smoke
  `alembic upgrade/downgrade 0008` sur **Postgres** avant déploiement (tests = `create_all`).

## S177 — Sondages de disponibilité

- Nouveau sous-système façon Doodle/TimeTree : `Poll` + `PollOption` + `PollVote`,
  conversion directe d'un sondage validé en `Event`.
- Réutilise `EventParticipant`/invitations existants pour le ciblage des votants.

## S178 — PWA + notifications push web + widgets + digest

- Service worker + Web App Manifest → installable sans app native (contourne le
  problème d'adoption mobile identifié).
- Push web (canal supplémentaire à 🔔+Telegram existants) pour les notifs par-personne
  de S174 et les listes de S176.
- Widgets = raccourcis PWA, une fois le manifest en place.
- Digest quotidien/hebdo (façon Cozi) par email (brique mail 6030) ou Telegram.

## S179 — Géolocalisation légère + export ICS/webcal

- Partage de position **ponctuel** (pas de tracking permanent) façon FamilyWall —
  sujet sensible côté vie privée, design dédié à l'ouverture du sprint (opt-in explicite,
  durée de partage limitée).
- Flux ICS abonnable (`webcal://`) en lecture seule pour ouvrir l'agenda dans une app
  tierce sans compte ni API custom.

## S180 — Chiffrement au repos (durcissement sécurité)

- Traité à part et en dernier : cross-cutting (touche tous les modèles), moins urgent
  en auto-hébergé (le serveur est chez l'utilisateur, pas un tiers) contrairement à
  TimeTree/FamilyWall SaaS. À réévaluer si des tiers au-delà de Marina rejoignent
  l'agenda.

## Hors périmètre / à clarifier au lancement

- **Saisie en langage naturel** (façon Fantastical) : l'assistant (Cœur) peut déjà créer
  des events en langage naturel via l'outil `agenda_creer_evenement` (LLM). Reste à
  clarifier si le besoin est une **barre de saisie rapide texte libre dans le dashboard
  web** (parsing local type chrono-node, sans passer par l'assistant) — à trancher au
  brainstorm du sprint concerné si jugé encore utile après S174→S180.
