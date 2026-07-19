# S182b — Onglet Agenda natif via proxy du Cœur (multi-user sans double login)

Date : 2026-07-19 · Suite de [[sprint-s182-s183-multiutilisateur-espaces]] · branche `s182-chacun-son-agenda`

## Décision (utilisateur, 2026-07-19)

Rendre l'onglet Agenda du dashboard **multi-utilisateur dans le navigateur** par une **vue native
servie via le proxy `/agenda/*` du Cœur** (déjà per-user après S182 : `_entetes()` porte le `sub`
de session), plutôt que par l'iframe `/app` (qui exige soit un 2e login PKCE, soit
`AUTH_ENABLED=true`). Aucune bascule de flag, pas de double login.

## État de départ

- L'onglet Agenda = **iframe** vers `/app` (brique). Avec `AUTH_ENABLED=false`, `/app` résout tout
  le monde sur `perso` → mono-user de fait.
- Le **proxy `/agenda/*` du Cœur** (`core/agenda.py` + `core/routers/agenda.py`) existe déjà et,
  depuis S182, porte l'identité de session (X-User-Id via `contexte_tenant`). Proxys présents :
  `lister_agendas` (calendriers+rôle), `lister_evenements` (agrégés, enrichis couleur/calendrier),
  `creer_evenement_dans`, `modifier_evenement`, `supprimer_evenement`, étiquettes, documents.
- **Manquent** pour le partage natif : créer un calendrier partagé + créer une invitation.

## Changements

### Backend — 2 proxys + 2 routes (Cœur)
- `core/agenda.py` : `creer_agenda(registre, nom, couleur, description)` → `POST /calendars` ;
  `creer_invitation(registre, calendar_id, role, expire_heures, email)` →
  `POST /calendars/{id}/invitations`. Tous deux via `_entetes()` (identité de session).
- `core/routers/agenda.py` : `POST /agenda/calendriers` et
  `POST /agenda/calendriers/{cal}/invitations` (mêmes gardes que les autres routes agenda,
  dépendance `_tenant` déjà posée sur le routeur).

### Front — vue native dans le dashboard (`core/routers/dashboard.py`)
Remplacer l'iframe `#agenda-iframe` par une vue native :
- **Barre « Mes agendas »** : `<select>` des calendriers (`GET /agenda/calendriers`, avec rôle) +
  bouton **« + Nouvel agenda »** (modale nom+couleur → `POST /agenda/calendriers`) + bouton
  **« Inviter »** (owner only → `POST /agenda/calendriers/{id}/invitations` → affiche le lien).
- **Grille mensuelle** des événements accessibles (`GET /agenda/evenements?debut&fin`), pastille
  couleur par calendrier ; navigation mois précédent/suivant.
- **Modale événement** : créer (`POST` via route existante) / titre, date, heure, calendrier.
- Garde le lien « Ouvrir dans un onglet ↗ » vers `/app` (repli riche, TimeTree/Google inchangés).
- Les panneaux Google/TimeTree (`g-panel`/`tt-panel`) restent tels quels.

## Sécurité / identité

Tout passe par la session web du Cœur (cookie S171) → `contexte_tenant` → `_entetes()` X-User-Id
→ branche S2S de l'agenda (honorée sous `CALENDAR_SERVICE_TOKEN`/`AGENDA_KEY`). Aucune identité
côté client, pas de JWT dans le navigateur pour l'agenda. `AUTH_ENABLED` reste `false`.

## Tests

- Backend : proxys `creer_agenda`/`creer_invitation` (FakeClient capture méthode/URL/headers +
  X-User-Id du contexte) ; routes `POST /agenda/calendriers*` (200/JSON).
- Front : le dashboard contient la vue native (`chargerAgenda` bâtit la grille, boutons Nouvel
  agenda/Inviter) et non plus seulement l'iframe ; `node --check` du script.

## Migration / LIVE

Aucune migration. Déploiement : rebuild core. Preuve navigateur : 2 comptes → 2 agendas ; créer
« Famille » + inviter depuis l'onglet, l'autre accepte via le lien.
