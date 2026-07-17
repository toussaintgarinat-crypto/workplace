# S180 — Chiffrement au repos (brique agenda) — design

Date : 2026-07-17
Sprint : S180 (dernier sprint du roadmap agenda best-in-class, voir
`docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`).
Périmètre : `briques/agenda/backend`.

## But

Chiffrer au repos le contenu humain sensible de la brique agenda, pour qu'un dump
de base / une sauvegarde / un accès DBA ne révèle ni les événements de la famille,
ni les positions géographiques, ni les emails, ni les numéros de fidélité. Défense
en profondeur : chiffrement **applicatif par champ** codé dans ce sprint + volume
disque chiffré noté comme tâche de déploiement HP (hors code).

Contexte : le primitif de chiffrement existe déjà et tourne — `vault.py` chiffre les
tokens OAuth Google en AES-GCM (clé dérivée de `VAULT_SECRET`). S180 étend ce « au
repos » au reste des données sensibles, en réutilisant la même primitive.

Modèle de menace visé (décision utilisateur, « les deux ») : auto-hébergé, la menace
principale est une **fuite de sauvegarde / dump / disque**, pas un tiers SaaS. Le
chiffrement par colonne protège les dumps et l'accès DBA ; le volume chiffré (infra,
déploiement) protège le disque volé.

## 1. Mécanisme — `TypeDecorator` SQLAlchemy transparent

Nouveau module `crypto.py` exposant la primitive AES-GCM **extraite de `vault.py`**
(pour que `vault.py` et les nouveaux types partagent exactement le même code de
chiffrement) et trois `TypeDecorator` :

- `Chiffre` — colonne sous-jacente `Text`. `process_bind_param` (écriture) chiffre la
  chaîne et la stocke en **base64** dans la colonne `Text`. `process_result_value`
  (lecture) déchiffre et rend la chaîne en clair. `None` reste `None` (colonnes
  nullable préservées).
- `ChiffreFloat` — pour `LivePosition.latitude/longitude`. Sérialise le float en
  chaîne (`repr`), chiffre, stocke en base64 dans une colonne `String`. Au read,
  déchiffre puis `float(...)`.
- `ChiffreJSON` — pour `EventActivityLog.details`. `json.dumps` → chiffre → base64 ;
  au read, déchiffre → `json.loads`. `None` reste `None`.

Le reste du code (routers, services, génération ICS, digest, boucle proactif du Cœur,
pont Google) **ne change pas** : il lit et écrit des valeurs en clair, la couche ORM
chiffre/déchiffre de façon transparente.

**Enveloppe versionnée.** Le blob chiffré est `version(1 octet) || nonce(12 octets)
|| ciphertext`, encodé base64 pour tenir dans une colonne texte. La version (`0x01`)
prépare une rotation de clé future : au read, on lira la version pour choisir la clé.
Aucune rotation n'est codée dans ce sprint (YAGNI) — seul l'octet de version est
réservé.

**Fail-closed.** Comme `vault.py`, toute écriture chiffrée lève si aucune clé n'est
configurée (voir §3) — on ne stocke jamais un champ sensible en clair par accident.

## 2. Champs chiffrés (périmètre complet)

Tous ces champs sont du texte libre / PII, **jamais** filtrés en `WHERE`, `ILIKE`,
`LIKE` ni triés en `ORDER BY` (vérifié par grep sur `routers/` + `services/`) — donc
zéro casse fonctionnelle.

| Modèle | Champs |
| --- | --- |
| `Event` | `title`, `description`, `location` |
| `EventComment` | `content` |
| `LivePosition` | `latitude`, `longitude` (géoloc), `label` |
| `UserProfile` | `email`, `display_name` |
| `CalendarInvitation` | `email` |
| `ShoppingListInvitation` | `email` |
| `LoyaltyCard` | `numero`, `note` |
| `AvailabilityPoll` | `title`, `description`, `location` |
| `PollVote` | `voter_name` |
| `EventActivityLog` | `user_nom`, `details` (JSON) |
| `ShoppingItem` | `name`, `note` |
| `ShoppingList` | `name` |

`UserProfile.display_name` et `LivePosition.label` ont été ajoutés après la revue
finale de branche : ce sont les mêmes contenus humains que les instantanés déjà
chiffrés (`EventActivityLog.user_nom`, `PollVote.voter_name` pour l'un ;
`latitude`/`longitude` pour l'autre) — les laisser en clair aurait défait le
chiffrement des instantanés dans un dump de base.

### Laissés en clair (justifié)

- Tous les `*_at` (`start_at`/`end_at` indexés en plage, `expires_at` indexé, etc.) —
  interrogés/triés par valeur.
- `user_id`, `created_by`, `uploaded_by`, `checked_by`, clés de jointure — indexées,
  utilisées en `WHERE`/join.
- Jetons-capacités : `ics_token`, `share_token`, tokens d'invitation, `guest_key` —
  **déjà des secrets aléatoires**, recherchés par égalité exacte (chiffrer casserait
  le lookup et n'ajoute rien : ce sont des capacités, pas des données).
- `external_id` (idempotence de sync, lookup par valeur).
- `Label.name` et `LoyaltyCard.enseigne` — triés par `order_by` (peu sensibles :
  noms de catégorie / d'enseigne ; le vrai secret de la carte est `numero`, chiffré).
- Couleurs, emoji, enums (`status`, `role`, `scope`, `format`, `kind`…), booléens,
  positions — non sensibles.

## 3. Gestion de clé — dédiée avec repli dérivé

Nouveau réglage `AGENDA_ENCRYPTION_KEY` dans `config.py`.

- **Si `AGENDA_ENCRYPTION_KEY` est posé** : la clé AES-GCM = `SHA-256(AGENDA_ENCRYPTION_KEY)`
  (même schéma que `vault.py`).
- **Sinon, repli** : dérive une sous-clé **distincte** de `VAULT_SECRET` via HKDF-SHA256
  avec `info="agenda-fields-v1"`. Résultat : jamais littéralement la même clé que le
  coffre OAuth (séparation des usages), mais **zéro friction** si le secret dédié n'est
  pas déployé.
- **Si ni l'un ni l'autre** : lève au premier chiffrement (fail-closed).

Le coffre OAuth (`vault.py`) continue d'utiliser `SHA-256(VAULT_SECRET)` directement,
inchangé. Rotation de clé = fast-follow (l'enveloppe versionnée §1 la prépare).

## 4. Migration des données existantes — Alembic `0012`

Le HP porte de vraies données (miroir TimeTree ~415 events, profils, etc.), donc on
chiffre **en place** plutôt qu'un déchiffrement paresseux tolérant.

- `upgrade()` : pour chaque table concernée, lit les lignes en clair et réécrit la
  valeur chiffrée base64. Les colonnes `Text`/`String` restent **inchangées** (le
  base64 y tient) → migration = pur `UPDATE`, pas d'`ALTER TYPE`.
- Exception `LivePosition.latitude/longitude` : `Float → String` (nécessaire pour
  stocker du ciphertext). Table éphémère (TTL court), quasi vide en pratique — la
  migration purge/ignore les positions expirées.
- `downgrade()` : déchiffre en place (et `String → Float` pour la position).
- La migration importe `crypto.py` et **exige** donc qu'une clé (§3) soit configurée
  au moment de l'`alembic upgrade` — documenté dans le README.
- **Smoke obligatoire avant déploiement** : `alembic upgrade 0012` puis `downgrade`
  sur **Postgres** réel (les tests unitaires utilisent `create_all`, pas la migration),
  comme pour les migrations 0006–0011.

## 5. Tests

- `crypto.py` : round-trip chiffre/déchiffre pour `Chiffre`/`ChiffreFloat`/`ChiffreJSON` ;
  enveloppe versionnée (octet de version correct, nonce unique par appel) ; dérivation
  HKDF déterministe et **distincte** de la clé du coffre ; `AGENDA_ENCRYPTION_KEY`
  prioritaire sur le repli ; fail-closed sans aucune clé ; `None` → `None`.
- Types ORM : persistance transparente — écrire un `Event`/`EventComment`/… puis relire
  rend le clair ; et une lecture SQL **brute** de la colonne montre un blob **≠** du
  plaintext (preuve que c'est bien chiffré en base).
- Non-régression : les suites agenda existantes (~325) restent vertes **sans
  modification** — c'est la preuve de transparence du `TypeDecorator`. En test, `create_all`
  crée directement les colonnes au type chiffré.
- Migration `0012` : test dédié d'aller-retour (semer des lignes en clair via SQL brut →
  `upgrade` → vérifier illisible en brut + lisible via ORM → `downgrade` → clair de
  nouveau). Exécuté au moins en SQLite ; smoke Postgres au déploiement (§4).

## 6. Défense en profondeur (hors code — déploiement HP)

Volume Docker de la base agenda sur disque chiffré (ou Postgres sur volume LUKS). À
ajouter au runbook `MIGRATION-HP.md`. **Pas** dans le périmètre code de ce sprint.

## 7. Fast-follow

- **Rotation de clé** réelle (l'enveloppe v1 la prépare : lire l'ancienne version,
  réécrire en nouvelle).
- **Pièces jointes** : `EventAttachment` stocke des fichiers en clair dans
  `ATTACHMENTS_DIR` — **non couvert** par le chiffrement de colonnes. Décision
  utilisateur 2026-07-17 : garder en fast-follow (chiffrer les fichiers sur disque plus
  tard).
- **Géocodage** futur de `Event.location` (fast-follow S179) : géocoder au write
  **avant** chiffrement (le service ne voit que du clair, ordre naturel).

## Convention

Design brainstormé à l'ouverture du sprint (roadmap S174→S180). Implémentation via
writing-plans → TDD subagent-driven. Commit en fin de sprint
([[feedback-commit-fin-de-sprint]]). LIVE différé, groupé après S180
([[feedback-live-differe-fin-s180]]).
