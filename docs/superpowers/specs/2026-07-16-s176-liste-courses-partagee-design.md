# S176 — Liste de courses/tâches partagée (façon Bring!) — design

**Date** : 2026-07-16
**Brique** : `briques/agenda`
**Roadmap** : `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md` §S176 ; mémoire
[[roadmap-s174-s180-agenda-best-in-class]].
**Statut** : design validé (brainstorm 2026-07-16), à implémenter.

## Objectif

Doter la brique agenda d'un sous-système de **listes partagées** façon **Bring!** :
catalogue visuel d'items (emoji, groupés par rayon, *tap-to-add*), cochage en temps réel
entre appareils (SSE), et notification par personne sur les changements. Couvre les
courses **et** les tâches génériques. But produit : que Marina (et d'autres) gèrent leurs
courses dans la brique plutôt que dans une app tierce, sans friction d'adoption.

## Décisions de cadrage (brainstorm 2026-07-16)

1. **Entité autonome** — une liste n'est PAS rattachée à un calendrier. Elle a sa propre
   table de membres, ses propres invitations, son propre canal SSE. (Choix utilisateur ;
   plus de code que « rattachée au calendrier » mais conceptuellement propre — une liste de
   courses n'est pas un calendrier.)
2. **Modèle unifié courses + tâches** — une seule table `ShoppingList` avec un champ
   `kind` (`courses` | `taches`). `courses` déverrouille le catalogue par rayon ; `taches`
   = simple checklist texte libre. Même moteur d'items, même cochage, même SSE.
3. **Catalogue emoji FR semé** — chaque entrée de catalogue = nom + emoji + rayon.
   Catalogue français par défaut semé au démarrage (zéro pipeline d'assets, self-hosted
   friendly). L'utilisateur enrichit avec ses propres items.
4. **SSE + push par personne** — le cochage/ajout se propage en direct via SSE **et**
   déclenche un push par-personne réutilisant le contrat `/pousser` de la brique
   `connexion` (S174).
5. **Outils LLM inclus** — les courses sont pilotables en parlant à l'assistant (nouvelles
   capacités au manifest).
6. **Partage par lien d'invitation** — miroir exact de `CalendarInvitation` (token +
   accept).

## Modèle de données — migration Alembic `0008`

Toutes les tables suivent les conventions ORM existantes (`models/orm.py`) : PK `String(36)`
UUID (`_uuid`), `DateTime` `server_default=func.now()`, FK `ondelete="CASCADE"` sauf mention.

### `ShoppingList`  (`shopping_lists`)
| colonne | type | notes |
|---|---|---|
| `id` | str(36) PK | uuid |
| `kind` | Enum(`courses`,`taches`, name=`list_kind`) | non-null, défaut `courses` |
| `name` | str(255) | non-null |
| `created_by` | str(255) | non-null (sub Keycloak) |
| `created_at` / `updated_at` | DateTime | server_default / onupdate |

Relations : `members`, `invitations`, `items` (toutes `cascade="all, delete-orphan"`).

### `ShoppingListMember`  (`shopping_list_members`)
Miroir de `CalendarMember`. `list_id` FK CASCADE ; `user_id` str(255) index ; `role`
Enum(`owner`,`editor`,`viewer`, name=`list_member_role`) défaut `viewer` ; `joined_at`.
Contrainte unique `(list_id, user_id)` = `uq_list_member`.

### `ShoppingListInvitation`  (`shopping_list_invitations`)
Miroir de `CalendarInvitation`. `list_id` FK CASCADE ; `token` str(36) unique défaut
`_uuid` ; `email` str(255) nullable ; `role` str(20) défaut `viewer` ; `created_by`
str(255) ; `expires_at` nullable ; `used_at` nullable ; `created_at`.

### `ShoppingItem`  (`shopping_items`)
| colonne | type | notes |
|---|---|---|
| `id` | str(36) PK | |
| `list_id` | str(36) FK CASCADE index | |
| `name` | str(255) | non-null |
| `emoji` | str(16) nullable | pour l'affichage |
| `rayon` | str(50) nullable | un des rayons fixes (courses) ; NULL pour tâches |
| `note` | str(255) nullable | quantité / précision (« x2 », « bio ») |
| `checked` | Boolean | défaut False |
| `checked_by` | str(255) nullable | qui a coché (dernier) |
| `checked_at` | DateTime nullable | |
| `added_by` | str(255) | non-null |
| `position` | Integer | défaut 0 — ordre d'affichage intra-rayon |
| `created_at` / `updated_at` | DateTime | |

### `CatalogItem`  (`catalog_items`)
Catalogue *tap-to-add*. `list_id` **nullable** : `NULL` = entrée **intégrée** (catalogue
FR par défaut, partagé, semé au boot) ; non-NULL = entrée **perso à une liste** (item
hors-catalogue mémorisé). `name` str(255) ; `emoji` str(16) ; `rayon` str(50) ; `created_by`
str(255) **nullable** (NULL pour les intégrés). Le catalogue vu par une liste =
`{intégrés} ∪ {perso de cette liste}`.
Contrainte unique partielle non portable SQLite→Postgres : on l'assure **applicativement**
(vérif « existe déjà (scope, name lower) ? » avant insert), pas par contrainte DB, pour
rester portable (SQLite tests / Postgres prod).

### Rayons (constante, pas une table)
Liste FR fixe dans `services/catalogue.py` :
`Fruits & légumes`, `Crèmerie`, `Boulangerie`, `Boucherie-Poissonnerie`, `Épicerie salée`,
`Épicerie sucrée`, `Boissons`, `Surgelés`, `Hygiène`, `Entretien`, `Bébé`, `Animaux`,
`Autre`. L'ordre de cette liste = l'ordre d'affichage des rayons dans le front.

## Catalogue FR semé — `services/catalogue.py`

- Constante `RAYONS: list[str]` (ordre d'affichage).
- Constante `CATALOGUE_DEFAUT: list[tuple[emoji, nom, rayon]]` — ~70 items courants
  (ex. `("🥛", "Lait", "Crèmerie")`, `("🍅", "Tomates", "Fruits & légumes")`,
  `("🥖", "Baguette", "Boulangerie")`…).
- `async def semer_catalogue(db) -> int` : idempotent. Garde par **count des intégrés**
  (`list_id IS NULL`) — si > 0, no-op ; sinon insère `CATALOGUE_DEFAUT`. Appelé au
  `lifespan` (comme le backfill S174), best-effort (un échec ne bloque pas le boot).
- `async def catalogue_pour_liste(db, list_id) -> list[CatalogItem]` : intégrés ∪ perso.
- `async def memoriser_item_perso(db, list_id, nom, emoji, rayon, user_id)` : ajoute un
  `CatalogItem` perso-liste si absent (dédup applicatif sur `(list_id, lower(name))`).

## Contrôle d'accès — `utils/access.py`

Ajouter, en miroir de `require_calendar_access` :
- `get_list_role(db, list_id, user_id) -> str | None` : `owner` si `created_by == user_id`,
  sinon rôle du `ShoppingListMember`, sinon None.
- `require_list_access(db, list_id, user_id, min_role="viewer") -> tuple[ShoppingList, str]` :
  404 si accès insuffisant (même sémantique « 404 not found » que les calendriers, pas 403,
  pour ne pas divulguer l'existence).

Le créateur d'une liste devient `owner` — comme les calendriers, l'owner dérive de
`created_by`, **pas** besoin d'une ligne `ShoppingListMember` pour le créateur (get_list_role
le renvoie owner directement). Les membres invités obtiennent une ligne member.

## API REST

### Listes — `routers/lists.py`
| méthode | chemin | rôle min | effet |
|---|---|---|---|
| GET | `/lists` | — | mes listes (créées ou membre), avec compteur d'items non-cochés |
| POST | `/lists` | — | créer `{kind, name}` ; créateur = owner |
| GET | `/lists/{id}` | viewer | détail liste + items (triés rayon puis position) |
| PATCH | `/lists/{id}` | editor | renommer |
| DELETE | `/lists/{id}` | owner | supprimer (CASCADE items/membres/invits) |

### Membres & invitations — `routers/lists.py` (miroir `members.py`/`invitations.py`)
| méthode | chemin | rôle min | effet |
|---|---|---|---|
| GET | `/lists/{id}/members` | viewer | membres + profils (nom/couleur via `UserProfile`) |
| POST | `/lists/{id}/invitations` | editor | crée un token `{role, email?, expire_heures?}` |
| POST | `/lists/invitations/{token}/accept` | — (authentifié) | rejoint la liste ; marque `used_at` ; refuse si expiré/déjà utilisé |

### Items — `routers/list_items.py`
| méthode | chemin | rôle min | effet |
|---|---|---|---|
| GET | `/lists/{id}/items` | viewer | items de la liste |
| POST | `/lists/{id}/items` | editor | ajoute un item : `{name, emoji?, rayon?, note?}` **ou** `{catalog_item_id}`. Si `name` hors catalogue → `memoriser_item_perso`. Anti-doublon : si un item non-coché de même `name` existe, incrémente/annote plutôt que dupliquer (comportement Bring!). |
| PATCH | `/lists/{id}/items/{item_id}` | editor | coche/décoche (`checked`) — pose `checked_by`/`checked_at` ; ou édite `name/note/rayon/emoji` |
| DELETE | `/lists/{id}/items/{item_id}` | editor | retire l'item |
| POST | `/lists/{id}/items/clear-checked` | editor | vide tous les cochés d'un coup |

### Catalogue — `routers/list_catalog.py`
| méthode | chemin | rôle min | effet |
|---|---|---|---|
| GET | `/lists/{id}/catalog` | viewer | catalogue (intégré ∪ perso) groupé par rayon, pour la grille tap-to-add |

Chaque mutation d'item publie sur SSE (§ suivant) et déclenche le push par-personne.

## SSE temps réel

- Canal dédié **`list:{list_id}:changes`** (distinct des canaux calendrier).
- `services/pubsub.py` : ajouter `async def publish_list_change(list_id, event_type, payload)`
  (copie du `publish_change` calendrier, autre préfixe de canal).
- `routers/sse.py` : ajouter `GET /sse/lists/{list_id}` (gaté `require_list_access` viewer),
  miroir du stream calendrier (mode dégradé sans Redis = ping toutes les 30 s).
- Types d'événements émis : `item.added`, `item.checked`, `item.unchecked`, `item.updated`,
  `item.deleted`, `checked.cleared`. Payload = l'item sérialisé (ou `{item_id}` pour delete).

## Push par personne — `services/notifications.py` (nouveau, dans la brique)

- `async def notifier_membres(db, liste, acteur_id, texte)` : POST **best-effort** vers
  `connexion /pousser` pour **chaque autre membre** de la liste (jamais l'acteur). Ne lève
  **jamais**. Config : `CONNEXION_URL` (base) + `CONNEXION_KEY` (`X-API-Key`). Si `CONNEXION_URL`
  absent → no-op silencieux (repli honnête, comme `_pousser_messagerie` du Cœur).
- Nom de l'acteur résolu via `UserProfile` (S174) ; repli sur l'user_id brut si pas de profil.
- Corps `{utilisateur: <uid_membre>, texte: "🛒 …"}` — le pont `connexion` résout les canaux
  liés de chaque personne (Telegram…).
- Déclencheurs : `item.added` (« 🛒 {acteur} a ajouté {item} à {liste} ») et `item.checked`
  (« ✅ {acteur} a coché {item} »). Pas de push sur décoche/édition (anti-bruit).
- Appelé en tâche best-effort après commit de la mutation (n'impacte pas la réponse HTTP).

**Décision d'architecture (→ ADR)** : la brique émet **directement** vers `connexion`,
contrairement à S174 où c'est le Cœur (`proactif.py`) qui pousse sur une base **temporelle**
(rappels d'événements). Ici l'ajout/cochage est **événementiel et instantané** : un poll du
Cœur introduirait un délai et ne saurait pas *quel* changement notifier. La brique reste
« surface de service » (ADR `agenda-surface-de-service`) mais gagne une dépendance sortante
optionnelle et config-gatée vers `connexion`. À consigner :
`docs/decisions/2026-07-16-listes-push-evenementiel.md`.

## Outils LLM — `manifest.json` + `routers/service.py`

Nouvelles capacités (préfixe `courses_`), toutes sur `/service/lists…`, avec la même
identité S2S pinnée `perso` (ADR agenda-surface-de-service) :

| capacité | méthode | chemin | action | rôle |
|---|---|---|---|---|
| `courses_consulter` | GET | `/service/lists` (+ `?list_id=` → items) | non | lecture des listes / items |
| `courses_creer_liste` | POST | `/service/lists` | non | crée une liste `{nom, kind?}` |
| `courses_ajouter` | POST | `/service/lists/{id}/items` | non | ajoute un item par `nom` (résout la liste courses par défaut si `list_id` omis) |
| `courses_cocher` | PATCH | `/service/lists/{id}/items/{item_id}` | non | coche/décoche |

`routers/service.py` gagne ces routes (réutilise la logique des routers REST, mais identité
`perso`). Le manifest déclare les capacités (le Cœur les expose comme outils). Description
soignée façon Bring! pour que l'assistant sache résoudre « ajoute du lait à la liste de
courses ».

## Front — `templates_app.py`

Nouvel onglet **« Listes »** dans l'appli web existante (`GET /app`, login PKCE) :
- **Colonne gauche** : mes listes (nom + badge nb non-cochés), bouton `+ Nouvelle liste`
  (choix courses/tâches), zone « rejoindre par lien ».
- **Vue liste** :
  - items **non cochés** groupés par rayon (ordre `RAYONS`), cochés **repliés** en bas
    (section « Déjà pris » avec bouton « Vider »).
  - Pour `courses` : bouton « + Ajouter » ouvre la **grille catalogue** (emoji par rayon,
    tap = ajout instantané) ; champ texte libre pour item hors-catalogue.
  - Pour `taches` : simple champ texte libre.
  - Tap sur un item = coche/décoche (optimiste + confirmé par SSE).
  - Pastille couleur du profil de qui a coché (via `UserProfile`).
- **Temps réel** : `EventSource` sur `/sse/lists/{id}` — applique add/check/delete/clear en
  direct (multi-appareils). Reconnexion auto en cas de coupure.

Style aligné sur l'appli agenda existante (même palette, même auth PKCE, même helper fetch
avec bearer).

## Tests — TDD, subagent-driven

Une suite ciblée par unité (chacune verte avant la suivante) :
1. `test_shopping_orm.py` — modèle + migration 0008 (create_all + colonnes/contraintes).
2. `test_shopping_access.py` — `require_list_access` (owner/editor/viewer, 404 sans accès).
3. `test_shopping_lists.py` — CRUD listes + membres + invitations (accept/expiré/rejoué).
4. `test_shopping_items.py` — ajout (par nom / catalog_item_id / anti-doublon), coche/décoche
   (checked_by/at), clear-checked, delete, gating.
5. `test_catalogue.py` — `semer_catalogue` idempotent, `catalogue_pour_liste` (intégré ∪
   perso), `memoriser_item_perso` (dédup).
6. `test_shopping_sse.py` — `publish_list_change` (canal correct) + endpoint SSE (connected).
7. `test_shopping_notifications.py` — `notifier_membres` : cible les autres membres, jamais
   l'acteur, no-op si `CONNEXION_URL` absent, ne lève jamais (connexion injoignable mockée).
8. `test_service_courses.py` — capacités `/service/lists…` (identité perso) + cohérence
   manifest (le test manifest existant `test_manifest_capacites.py` doit rester vert).
9. Front : au moins un smoke `test_app_web` (l'onglet Listes rend, JS présent).

Objectif : suite agenda reste verte (194 → +N), `make test-core` reste à 439.

## Hors périmètre (fast-follow)

- Import de recettes en un clic (roadmap : « optionnel »).
- Templates de listes sauvegardées (« courses hebdo type ») — YAGNI pour l'instant ;
  le catalogue perso couvre déjà le *tap-to-add* récurrent.
- Push web / PWA (S178) — ici on réutilise seulement le canal `connexion` existant.
- Quantités structurées / unités (on reste sur `note` texte libre).
- Chiffrement au repos (S180).

## Risques & points d'attention

- **Portabilité SQLite/Postgres** : contrainte d'unicité catalogue gérée applicativement
  (pas de contrainte partielle DB). Migration 0008 à smoke-tester `alembic upgrade/downgrade`
  sur Postgres avant déploiement (comme noté pour 0007).
- **Dépendance sortante `connexion`** : nouvelle, mais optionnelle et best-effort — un push
  KO ne casse jamais une mutation. Config `CONNEXION_URL`/`CONNEXION_KEY` à documenter au
  déploiement (README brique).
- **Identité S2S `perso`** sur `/service` : les outils LLM créent/cochent en tant que `perso`
  (cohérent ADR agenda-surface-de-service) — le multi-user réel des listes passe par l'appli
  web PKCE, pas par l'assistant.
