# S177 — Sondages de disponibilité (façon Doodle/TimeTree) — design

**Sprint** : S177 (roadmap `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`).
**Brique** : `agenda` (backend port 8400). **LIVE différé** (voir mémoire
`feedback-live-differe-fin-s180`).

## Problème

Fixer une date à plusieurs (dîner, réunion famille/chantier) suppose aujourd'hui un
aller-retour manuel. Doodle/TimeTree résolvent ça avec un **sondage** : l'organisateur
propose N créneaux, chacun vote sa disponibilité par créneau, l'organisateur voit la
grille et tranche. Notre valeur en plus vs Doodle : **la finalisation crée directement
l'événement dans l'agenda** avec les votants « oui » pré-ajoutés comme participants —
boucle fermée sondage → agenda, dans le même produit.

## Décisions produit (validées avec l'utilisateur, 2026-07-16)

1. **Participation = lien public à jeton + membres connectés** (vrai modèle Doodle).
   Quiconque a le lien vote en donnant juste un nom (aucun compte requis → adoption
   Marina & co) ; un utilisateur connecté qui ouvre le lien voit son vote attribué à
   son profil.
2. **Finaliser crée l'événement agenda** : choisir le créneau gagnant crée un `Event`
   (titre/lieu/description repris du sondage) et pré-ajoute comme participants les
   votants « oui » **qui ont un compte** (les invités anonymes ne peuvent pas être
   participants — limitation honnête, notée).
3. **Réponses à trois états** : `oui` / `si_besoin` / `non` (yes / if-needed / no).

## Modèle de données (migration `0009`)

Sous-système autonome, aucune modification des tables existantes.

- **`availability_polls`** — le sondage.
  `id`, `title`, `description?`, `location?`, `created_by` (organisateur),
  `calendar_id?` (FK `calendars` `ON DELETE SET NULL` — cible de finalisation, sinon
  calendrier par défaut de l'organisateur au moment de finaliser), `status`
  Enum(`open`,`closed`) défaut `open`, `final_slot_id?`, `final_event_id?`,
  `share_token` (unique, = capacité du lien public), `expires_at?`, timestamps.
- **`poll_slots`** — un créneau proposé. `id`, `poll_id` (FK CASCADE, index),
  `start_at`, `end_at`, `position`.
- **`poll_votes`** — le vote d'une personne sur un créneau. `id`, `poll_id` (FK CASCADE,
  dénormalisé pour regrouper par votant), `slot_id` (FK CASCADE, index),
  `voter_id?` (user_id si connecté, NULL si invité), `voter_name` (snapshot du nom
  affiché), `guest_key?` (uuid stable pour regrouper/rééditer les votes d'un invité
  anonyme), `value` Enum(`oui`,`si_besoin`,`non`), timestamps.

**Identité de votant** = `voter_id` (membre) OU `guest_key` (invité). Un **bulletin**
couvre tout le sondage d'un coup (Doodle) : à la soumission on **remplace** tous les
votes de cette identité pour ce sondage (delete + insert), ce qui garantit « un
bulletin par personne » sans contrainte unique fragile côté anonyme.

## API

Gestion (organisateur, JWT/S2S) :
- `GET /polls` — mes sondages (organisateur) + résumé.
- `POST /polls` — créer {title, description?, location?, calendar_id?, slots:[{start_at,end_at}], expire_heures?}.
- `GET /polls/{id}` — vue organisateur : sondage + créneaux + **grille complète**
  (votants × créneaux) + tallies. Réservé `created_by`.
- `PATCH /polls/{id}` — éditer titre/desc/lieu (organisateur, sondage ouvert).
- `POST /polls/{id}/slots` / `DELETE /polls/{id}/slots/{slot_id}` — gérer les créneaux (ouvert).
- `DELETE /polls/{id}` — supprimer (organisateur).
- `POST /polls/{id}/finalize` {slot_id, calendar_id?} — crée l'`Event`, pré-ajoute les
  votants « oui » ayant un compte, passe le sondage `closed`, renseigne
  `final_slot_id`/`final_event_id`. Renvoie {event_id, calendar_id}.

Vote (public, par jeton — attribue au membre si connecté) :
- `GET /polls/token/{share_token}` — vue votant (sondage + créneaux + grille + tallies).
- `POST /polls/token/{share_token}/vote` {nom?, guest_key?, votes:[{slot_id,value}]} —
  soumet/remplace le bulletin. Membre connecté ⇒ attribué (nom du profil) ; sinon
  invité ⇒ `nom` requis, renvoie `guest_key` à réutiliser pour rééditer.
- `GET /polls/p/{share_token}` — **page HTML de vote** autonome (gabarit `page_sondage`,
  sans compte), sur le modèle de `page_invitation`.

Temps réel : canal `poll:{id}:changes` (`publish_poll_change`, best-effort Redis) émis
sur vote/finalisation ; SSE public `GET /sse/polls/{share_token}` (le jeton = capacité,
pas d'auth) → la grille se met à jour en direct pour tous ceux qui ont le lien.

Surface LLM (`/service`, contrat français, manifest **v1.3.0**) :
- `sondage_consulter` GET `/service/polls` — mes sondages ouverts + nb de votants.
- `sondage_creer` POST `/service/polls` {titre, creneaux:[{debut,fin}], description?, lieu?}
  — renvoie l'id + le lien public à transmettre.
- `sondage_finaliser` POST `/service/polls/{poll_id}/finalize` {creneau_id} — **action**
  (crée l'événement), `confirme=true` requis côté Cœur.

## Accès / sécurité

- `require_owned_poll(db, poll_id, user_id)` → 404 si le sondage n'appartient pas à
  l'appelant (ne divulgue pas l'existence, comme `require_list_access`).
- La vue et le vote publics passent par `share_token` (capacité) — jamais par `poll_id`.
- Vote authentifié optionnel : `get_optional_user` (renvoie `None` au lieu de 401) pour
  attribuer un vote à un membre connecté sur l'endpoint public sans casser le flux invité.

## Hors périmètre (fast-follow)

- Notifier les votants à la finalisation (push par personne façon S174/S176) — noté,
  pas fait ici pour borner le sprint.
- `si_besoin` ne pèse pas différemment dans le tri auto ; l'organisateur tranche à l'œil.
- Créneaux « journée entière » (all-day) — les créneaux sont datés/heurés pour v1.
- Fermeture auto à `expires_at` (le lien expire pour voter, le sondage reste consultable).

## Tests (TDD)

ORM (création/cascade), CRUD organisateur + gate 404, vote membre (remplace bulletin),
vote invité (guest_key stable, réédition), tallies/grille, finalize (event créé +
participants « oui » membres + statut closed + garde ouvert/propriétaire), surface
`/service` sondage_*, parité manifest (maj `test_manifest_capacites`).
