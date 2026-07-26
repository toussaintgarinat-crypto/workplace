# Roadmap S171→S177 — brique agenda "best-in-class"

But : égaler/dépasser TimeTree (chat, couleurs, invitations — déjà en base) + combler les
gaps identifiés vs TimeTree/Google Calendar/Cozi/FamilyWall/Fantastical/Bring!, pour que
Marina (et d'autres) utilisent la brique agenda sans revenir sur TimeTree.

Statut : **BLOQUÉ sur préalable** (backlog validé avec l'utilisateur 2026-07-15). Au
brainstorm de lancement de S171 (2026-07-15), constat que « rappels par personne »
suppose une vraie notion de personne (nom + canal de notif), inexistante aujourd'hui —
l'agenda est mono-user pinné sur `AGENDA_USER_ID="perso"` (ADR S168,
agenda-surface-de-service) et le Cœur lui-même n'a **aucune authentification
utilisateur** (`core/routers/dashboard.py` tourne en accès direct). Ce préalable est
traité comme une épopée séparée — voir
[[epopee-identite-multiutilisateur-coeur]] / `docs/sprints/S171-S173-epopee-identite-multiutilisateur-coeur.md`
— qui **emprunte les numéros S171→S173**. Ce roadmap agenda ne redémarre qu'une fois
l'épopée livrée : ses propres numéros de sprint (S171 ici = rappels par personne) ne
seront donc actifs qu'après S173 de l'épopée, même si le document garde S171 comme label
interne pour ne pas avoir à retoucher les renvois croisés (S172→S177) à chaque fois qu'un
préalable est inséré ailleurs. Chaque sprint sera brainstormé en détail (design doc
dédié) à son lancement — ce document fixe le découpage et l'ordre, pas les specs fines.

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
[préalable externe : épopée identité multi-utilisateur du Cœur, S171→S173]
   └─> S171 (notifs par personne + présence/chat exposés + journal d'activité)
        └─> S172 (récurrence avancée, indépendant, peut glisser avant/après S171)
        └─> S173 (liste de courses, réutilise notifs S171)
        └─> S174 (sondages de disponibilité, réutilise participants existants)
             └─> S175 (PWA + push web + widgets + digest — canal de notif mobile,
                        bénéficie de tout ce qui précède)
        └─> S176 (géoloc légère + export ICS, indépendants entre eux)
S177 (chiffrement au repos — durcissement sécurité, en dernier, cross-cutting)
```

## S171 — Notifications par personne + présence/chat exposés + journal d'activité

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

## S172 — Récurrence avancée

- `Event.recurrence_rule` existe en base mais n'est expansé nulle part (vérifié :
  aucune référence RRULE dans `routers/events.py`). Implémenter l'expansion RRULE réelle
  + gestion des exceptions ("tous les lundis sauf le 25").

## S173 — Liste de courses/tâches partagée (façon Bring!)

- Nouveau sous-système : `ShoppingList` + `ShoppingListItem`, cochage temps réel (SSE
  déjà dispo dans la brique), catalogue d'items visuel (icônes, tap-to-add), templates
  par rayon de magasin.
- Notifications sur ajout/cochage réutilisent l'infra par-personne de S171.
- Import de recettes en un clic = optionnel, à évaluer à l'ouverture du sprint (ROI vs
  effort).

## S174 — Sondages de disponibilité

- Nouveau sous-système façon Doodle/TimeTree : `Poll` + `PollOption` + `PollVote`,
  conversion directe d'un sondage validé en `Event`.
- Réutilise `EventParticipant`/invitations existants pour le ciblage des votants.

## S175 — PWA + notifications push web + widgets + digest

- Service worker + Web App Manifest → installable sans app native (contourne le
  problème d'adoption mobile identifié).
- Push web (canal supplémentaire à 🔔+Telegram existants) pour les notifs par-personne
  de S171 et les listes de S173.
- Widgets = raccourcis PWA, une fois le manifest en place.
- Digest quotidien/hebdo (façon Cozi) par email (brique mail 6030) ou Telegram.

## S176 — Géolocalisation légère + export ICS/webcal

- Partage de position **ponctuel** (pas de tracking permanent) façon FamilyWall —
  sujet sensible côté vie privée, design dédié à l'ouverture du sprint (opt-in explicite,
  durée de partage limitée).
- Flux ICS abonnable (`webcal://`) en lecture seule pour ouvrir l'agenda dans une app
  tierce sans compte ni API custom.

## S177 — Chiffrement au repos (durcissement sécurité)

- Traité à part et en dernier : cross-cutting (touche tous les modèles), moins urgent
  en auto-hébergé (le serveur est chez l'utilisateur, pas un tiers) contrairement à
  TimeTree/FamilyWall SaaS. À réévaluer si des tiers au-delà de Marina rejoignent
  l'agenda.

## Hors périmètre / à clarifier au lancement

- **Saisie en langage naturel** (façon Fantastical) : l'assistant (Cœur) peut déjà créer
  des events en langage naturel via l'outil `agenda_creer_evenement` (LLM). Reste à
  clarifier si le besoin est une **barre de saisie rapide texte libre dans le dashboard
  web** (parsing local type chrono-node, sans passer par l'assistant) — à trancher au
  brainstorm du sprint concerné si jugé encore utile après S171→S177.
