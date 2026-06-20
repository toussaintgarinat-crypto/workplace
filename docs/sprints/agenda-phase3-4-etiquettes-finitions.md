# Sprint Agenda « façon TimeTree » — Phase 3 & 4 (partie restante)

> **Statut** : 📋 **PRÉPARÉ — à lancer**. Suite directe des phases livrées.
> **Prérequis (déjà faits, PROUVÉ LIVE 2026-06-20)** : vue calendrier mois/semaine +
> navigation, modale événement (titre/dates/journée/calendrier/**couleur libre**/lieu/
> notes/**rappels multi**), **📎 documents** (upload/download/suppr) et **💬 commentaires** ;
> pont TimeTree lecture seule avec couleurs par étiquette ; rappels configurables 🔔+Telegram.

## Objectif

Compléter l'agenda pour qu'il soit pleinement « façon TimeTree » :
- **Phase 3** — **étiquettes nommées éditables** (les vraies *catégories* TimeTree :
  créer ses labels nommés + couleur, les réutiliser et filtrer dessus). Aujourd'hui il n'y
  a qu'une **couleur libre** par événement (pas de catégorie nommée réutilisable).
- **Phase 4** — finitions : sidebar calendriers afficher/masquer, filtre par étiquette,
  vue semaine en grille horaire, participants, récurrence, mémos, glisser-déposer.

Rappel d'architecture : le **backend de la brique agenda est déjà très complet**
(events CRUD + `color`/`all_day`/`recurrence_rule`/`rappels`, attachments, comments,
participants, calendars, membres/invitations). Le seul vrai ajout backend du sprint =
le modèle **Label** (P3) et, si on fait la récurrence, l'**expansion des occurrences** (P4).

---

## Phase 3 — Étiquettes nommées éditables (catégories)

### Brique agenda (backend)
- **`models/orm.py`** : nouveau modèle `Label` (`id`, `calendar_id` FK→calendars CASCADE,
  `name`, `color`, `created_at`) ; relation `Calendar.labels`. Ajouter à `Event` un champ
  `label_id: str | None` (FK→labels, `ondelete=SET NULL`, nullable, index).
- **Migration `alembic/versions/0005_labels.py`** : `create_table labels` + `add_column
  events.label_id` + index. ⚠️ Déploiement : la DB SQLite existante (volume `agenda_data`)
  ne reçoit pas la colonne via `create_all` → **ALTER manuel** comme pour `rappels`
  (`ALTER TABLE events ADD COLUMN label_id VARCHAR`).
- **`models/schemas.py`** : `LabelCreate/Update/Out` ; `EventOut`/`EventUpdate` gagnent
  `label_id` ; idéalement `EventOut` embarque `label` résolu `{name, color}` (sinon le
  front résout via la liste des labels).
- **`routers/labels.py`** (miroir de `routers/calendars.py` pour le contrôle d'accès
  `require_calendar_access`) : `GET /calendars/{cal}/labels`, `POST`, `PATCH /labels/{id}`,
  `DELETE /labels/{id}`. Enregistrer dans `main.py`.
- **Couleur dérivée** : si `event.label_id` est posé, la couleur d'affichage = celle du
  label ; sinon repli sur `event.color` (couleur libre actuelle). Garder les deux.
- **Import TimeTree** (option recommandée) : à la synchro, créer/mettre à jour des `Label`
  à partir de `get_labels()` (déjà récupérés) pour le calendrier « TimeTree », et poser
  `event.label_id` → la **légende affiche les noms** des catégories TimeTree, pas seulement
  des couleurs. (`services/timetree_calendar.py`.)

### Cœur (proxys + agrégation)
- **`core/agenda.py`** : helpers `lister_etiquettes(cal)`, `creer_etiquette`,
  `modifier_etiquette`, `supprimer_etiquette` ; `lister_evenements` enrichit déjà chaque
  event de `couleur` → ajouter `etiquette` (nom) si `label_id`.
- **`core/main.py`** : proxys `GET/POST /agenda/calendriers/{cal}/etiquettes`,
  `PATCH/DELETE /agenda/etiquettes/{id}`.

### Front (dashboard)
- **Modale événement** : remplacer/compléter la palette de couleurs libre par un
  **sélecteur d'étiquette** (liste des labels du calendrier choisi) + « + nouvelle
  étiquette » inline (nom + couleur) ; choisir une étiquette fixe la couleur. Garder
  l'option « couleur libre / aucune étiquette ».
- **Mini-gestion des étiquettes** (créer/renommer/recolorer/supprimer) : petit panneau
  accessible depuis la toolbar ou la modale.
- **Légende** des étiquettes au-dessus du calendrier (base du filtre P4).

### Tests
- Brique : `test_labels.py` (CRUD label, event hérite la couleur du label, suppression
  label → `label_id` SET NULL). Cœur : `test_agenda_etiquettes_proxys.py` (httpx mocké).

---

## Phase 4 — Finitions TimeTree (par ordre de valeur/coût)

1. **Sidebar calendriers + filtre étiquette** (client-only, peu coûteux) : afficher/
   masquer chaque calendrier (Perso/TimeTree/Google/partagés) et filtrer par étiquette
   en cliquant la légende ; état en mémoire côté navigateur.
2. **Glisser-déposer** un événement entre les jours (replanifie via `PATCH` dates) —
   geste très « calendrier ». Manuel = `agenda.deplacer_evenement` déjà dispo.
3. **Vue semaine en grille horaire** (heures en lignes, events positionnés/redimensionnés)
   — plus gros morceau front que la vue semaine « liste » actuelle.
4. **Participants** : UI pour voir/inviter qui vient (backend `routers/participants.py`
   déjà prêt : statut pending/accepted/declined/maybe).
5. **Événements récurrents** : exposer `recurrence_rule` (RRULE simple : quotidien/hebdo/
   mensuel/annuel). ⚠️ **Décision à trancher** : la brique stocke `recurrence_rule` mais
   `list_events` **n'expanse pas** les occurrences → soit **expansion backend** sur la
   fenêtre demandée (`python-dateutil` `rrule`, recommandé pour rester cohérent avec les
   rappels/agrégation), soit expansion **côté client**. C'est l'item le plus lourd.
6. **Mémos / notes du jour** (le « Keep » de TimeTree) : note légère attachée à une date
   (sans créneau). Peut réutiliser un event `all_day` taggé, ou un petit modèle dédié.

---

## Risques & décisions à trancher (avant de coder)

- **Récurrence** : expansion backend vs client (recommandé : backend `dateutil.rrule`).
- **Étiquettes importées TimeTree** : crée-t-on des `Label` au sync pour nommer la légende ?
  (recommandé oui — peu coûteux, gros gain de lisibilité).
- **Étiquettes vs couleur libre** : garder les deux (étiquette nommée OU couleur ponctuelle) ?
  (recommandé oui, comme aujourd'hui en repli.)

## Déploiement (rappels des pièges du projet)

- Code **figé dans l'image Docker** → **rebuild + recreate** `agenda` (P3 = changement
  brique) **et** `core` (front + proxys). Dashboard servi sur **`/dashboard`**.
- **Migration** : `create_all` n'altère pas une table existante → **`ALTER TABLE events
  ADD COLUMN label_id`** sur `/data/calendar.db` (volume `agenda_data`), comme fait pour
  `rappels`. La table `labels` (nouvelle) sera bien créée par `create_all`.
- `AGENDA_VAULT_SECRET` vit dans **`briques/agenda/.env`** (pas le `.env` racine).

## Vérification (end-to-end)

1. `pytest` brique + cœur verts.
2. Rebuild agenda + core ; ALTER `label_id`.
3. Créer une étiquette « Famille » (couleur) → l'assigner à un événement → l'event prend la
   couleur ; la légende affiche « Famille ».
4. Masquer le calendrier TimeTree → ses events disparaissent ; filtrer sur une étiquette.
5. (Si fait) glisser un event d'un jour à l'autre → dates mises à jour ; créer un event
   récurrent hebdo → occurrences affichées sur plusieurs semaines.

## Découpage en livraisons (anti-dispersion)

- **Livraison A** = Phase 3 complète (étiquettes nommées éditables, import TimeTree nommé).
  ✅ **LIVRÉE + PROUVÉE LIVE 2026-06-20** (tests verts : brique 58/58, Cœur 5+5+4 ;
  rebuild Docker agenda+core faits, `ALTER TABLE events ADD COLUMN label_id VARCHAR` posé
  sur le volume `agenda_data`, table `labels` créée par `create_all`). Preuve LIVE bout-en-bout
  via l'API du Cœur (:5100) : créer étiquette « Famille » → l'assigner à un event → la couleur
  du label (#ff0000) **prime** sur la couleur libre (#abcdef) + `etiquette: Famille` résolu ;
  suppression du label → l'event survit, `label_id` remis à NULL. Décisions tranchées =
  recommandations du doc (import TimeTree nommé = oui, étiquette **ET** couleur libre = oui).
- **Bonus 2026-06-20** : **pont Google branché au dashboard** comme TimeTree (proxys Cœur
  `GET /agenda/google/status|connect`, `POST /agenda/google/sync`, `DELETE …/disconnect` +
  panneau « Google Agenda » dans l'onglet Agenda). Backend brique déjà là (S27, OAuth) ;
  différence : Google = consentement OAuth (bouton → onglet Google → retour), pas email/mdp.
  Actif si `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` configurés (sinon panneau « non configuré »).
  Tests Cœur `test_agenda_google_proxys.py` 4✓.
- **Livraison B** = Phase 4 items 1-2 (sidebar/filtre + glisser-déposer).
- **Livraison C** = Phase 4 items 3-6 (grille horaire, participants, récurrence, mémos),
  la récurrence pouvant être un sprint à part vu son coût.

> Préférence utilisateur : **committer chaque sprint d'un coup une fois bouclé**, pas de
> commit en cours de route.
