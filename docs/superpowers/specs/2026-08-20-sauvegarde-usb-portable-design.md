# Sauvegarde portable sur clé USB (à la demande)

## Contexte

Le HP héberge le stack Docker complet de Workplace. Un plan antérieur
(`docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md`) a câblé une réplication
**continue** vers S3 (Litestream pour `agenda`/`donnees`, WAL-G pour `memoire-db`/`gateway-db`)
mais ne l'a jamais branchée en prod — les 4 sidecars concernés tournaient en échec sur le HP
faute de cible S3 configurée (`Error: bucket required for s3 replica` / `Failed to find any
configured storage`), sans impact sur les services principaux.

En reconnectant le HP (2026-08-20), ce trou a été découvert et les 4 sidecars ont été arrêtés
proprement (`docker stop`). L'utilisateur refuse tout stockage cloud US (souveraineté des
données) et n'a pas besoin de réplication continue : son usage réel est **ponctuel** — brancher
une clé USB sur le HP, prendre un instantané, l'emporter sur un autre PC, restaurer,
retravailler, ramener la clé avec les nouvelles données. Ce document remplace, pour cet usage,
l'approche « réplication continue vers S3 » par une approche « instantané à la demande, sur
support local ».

Inventaire réel effectué sur le HP le 2026-08-20 (`docker ps` + recherche de fichiers) :
**6 bases Postgres** (`memoire-memoire-db-1`, `gateway-db-1`, `keycloak-db`, `oria-db-1`
patroni, `peertube-db`, `forge-forge-db-1`) et **~22 bases SQLite** réparties sur 19 conteneurs
(dont 4 dans `core-core-1` lui-même : `rappels.db`, `livraisons.db`, `session_registre.db`,
`horloge.db`).

## Non-objectifs

- **Pas de réplication continue** — les sidecars Litestream/WAL-G existants restent arrêtés ;
  ce plan ne les réactive pas et n'y touche pas (ils pourront resservir un jour si un vrai
  besoin de RPO continu apparaît, avec un vrai stockage S3/B2 — décision différée).
- **Pas d'intégration Google Drive/OAuth** — le bouton d'export du `.env` sort juste le
  contenu du fichier (affichage/téléchargement) ; c'est l'utilisateur qui le range ensuite où
  il veut. Aucun jeton, aucune connexion à un service tiers.
- **Pas de secrets sur la clé USB** — le `.env` (API keys, mots de passe, secrets JWT) n'est
  **jamais** écrit sur la clé de sauvegarde des bases. Il est géré par un canal séparé, choisi
  et opéré par l'utilisateur (Drive, autre clé, etc.), hors périmètre de ce plan.
- **Pas d'historique d'instantanés** — la clé ne porte qu'**un seul** instantané à la fois,
  écrasé à chaque nouvelle sauvegarde. Pas de rétention à gérer, pas de purge à programmer.
- **Pas de script de restauration à lancer manuellement en régime normal** — la restauration
  passe par la même capacité assistant que la sauvegarde, une fois le Cœur démarré sur la
  machine cible (cf. « Bootstrap machine neuve » plus bas pour la seule partie réellement
  manuelle : avant que le Cœur existe).
- **Qdrant (`forge-qdrant-1`) hors périmètre** — c'est un moteur vectoriel, pas une base
  Postgres/SQLite ; il n'est pas couvert par la découverte dynamique de ce plan. Limite
  documentée, à traiter séparément si un jour nécessaire (comme Oria/Patroni l'était dans le
  plan RPO d'origine, avant d'être finalement inclus ici côté Postgres classique).

## Architecture

Un nouveau module natif dans `core`, pas une brique séparée : `core/routers/sauvegarde_usb.py`
(+ un module de logique, ex. `core/sauvegarde_usb.py`, à trancher en phase de plan selon la
convention `routers/` vs racine déjà en usage dans `core/`).

**Pourquoi dans `core` et pas une nouvelle brique** : `core` monte déjà le socket Docker
(`core/docker-compose.yml:87`, actuellement utilisé par `config_assistant.py` pour redémarrer
la Gateway après un changement de clé). Étendre l'usage d'un accès déjà présent évite de
dupliquer un accès root-équivalent au host. L'opération elle-même est par nature transverse à
tout le stack (comme `/sante-globale` l'est déjà), ce qui en fait un candidat naturel pour une
capacité « noyau » plutôt que pour une brique dédiée.

Alternatives écartées :
- **Brique dédiée avec son propre socket Docker** — isolement un peu plus net, mais duplique
  un accès déjà existant sur `core` pour un gain de sécurité marginal, et ajoute un conteneur
  + un manifest + un cycle de build pour une action rare.
- **Script hôte pur déclenché en SSH depuis un conteneur** — évite d'étendre l'usage du socket
  de `core`, mais introduit un nouveau canal (SSH conteneur→hôte) qui n'existe nulle part
  ailleurs dans le projet, pour un gain limité.

## Découverte dynamique des sources (pas de liste figée)

Le module interroge l'API Docker (via le socket) plutôt que de coder en dur la liste des 25+
bases trouvées le 2026-08-20 — cette liste serait fausse dès la prochaine brique ajoutée.

Pour chaque conteneur **actif** :
- **SQLite** : recherche d'un `*.db` sous `/data` (motif déjà vérifié en pratique lors de
  l'inventaire du 2026-08-20 : `find /data -maxdepth 2 -iname "*.db"` dans chaque conteneur).
- **Postgres** : détection par image (`postgres:*`, `*-walg`, ou toute image dont le process
  écoute sur 5432 — motif à affiner en phase de plan ; les 6 bases connues suivent ce motif).

Un conteneur arrêté au moment de la sauvegarde est simplement absent de l'instantané (pas
d'échec global) — noté dans le manifeste comme « ignoré (conteneur arrêté) ».

## Sauvegarde (`sauvegarde_usb_lancer`)

1. **Garde-fou avant toute écriture** : vérifie qu'un fichier sentinelle
   `.cle-sauvegarde-workplace` existe déjà à la racine du point de montage configuré (posé une
   fois manuellement sur la clé, à l'installation). Absence de sentinelle → refus net, rien
   n'est écrit ailleurs. Ce garde-fou empêche une écriture silencieuse sur le disque interne du
   HP si le point de montage existe mais que la clé n'est en réalité pas branchée (dossier vide
   plutôt que vraie clé montée).
2. **Vérification d'espace** : taille cumulée estimée des sources vs. espace libre sur la
   clé — abandon propre et message clair si insuffisant, avant d'avoir rien écrit.
3. **SQLite** → `docker cp <conteneur>:/data/<fichier>.db <dest>/<brique>/`.
4. **Postgres** → `docker exec <conteneur> pg_dump -U <user> <db>` redirigé vers
   `<dest>/<brique>/<db>.sql`. Choix explicite : dump **logique** (SQL portable), pas de copie
   brute du répertoire `/var/lib/postgresql/data` — une copie brute lierait la restauration à
   la même version/architecture Postgres, ce qui casserait l'objectif « restaurer sur un autre
   PC ».
5. **Manifeste** : `manifest.json` à la racine de l'instantané — une entrée par source
   (brique, type `sqlite`/`postgres`, chemin/nom de fichier, taille, horodatage). C'est ce
   manifeste, et lui seul, qui pilote la restauration — aucune liste figée côté code de
   restauration non plus.
6. **Écrasement** : l'instantané précédent est remplacé (un seul à la fois), pas de dossier
   horodaté à gérer.
7. **Confirmation** : capacité assistant `action: true`, gate `accord_action.py` (S222) — un
   vrai tour de parole humain requis avant exécution, même mécanisme que les autres actions
   sensibles du projet.

## Restauration (`sauvegarde_usb_restaurer`)

Symétrique de la sauvegarde, même module : lit `manifest.json` sur la clé montée, puis par
entrée — `docker cp` le `.db` dans le volume Docker de la brique cible (créé si besoin), ou
`docker exec -i <conteneur> psql -U <user> <db> < dump.sql` pour Postgres (conteneur démarré à
vide au préalable, cf. bootstrap ci-dessous). Même capacité assistant, même gate de
confirmation.

**Condition préalable** : le Cœur doit déjà tourner sur la machine cible pour que cette
capacité soit joignable — ce qui n'est pas le cas juste après un `git clone` sur un PC neuf
(cf. section suivante pour cette étape, hors périmètre de la capacité assistant elle-même).

## Bootstrap sur une machine neuve (hors capacité assistant)

Avant que le Cœur existe, aucune capacité assistant n'est joignable — il faut, une seule fois
et à la main (ou via un agent de code type Claude Code/OpenCode, à qui l'utilisateur demande
« installe Workplace ici ») :
1. Installer Docker.
2. Cloner le dépôt GitHub.
3. Poser un `.env` (récupéré par le bouton d'export, rangé séparément par l'utilisateur — cf.
   non-objectifs).
4. Démarrer au moins le Cœur (`docker compose up` dans `core/`).

Une fois le Cœur debout (même avec des bases vides), la restauration redevient pilotable par
l'assistant (« restaure depuis la clé »).

**Livrable documentaire de ce plan** : un guide d'installation sur le modèle de
`MIGRATION-HP.md`, décrivant ces 4 étapes assez explicitement pour qu'un agent de code puisse
les suivre sans supervision ligne à ligne.

## Export du `.env` (`env_exporter`)

Bouton/capacité séparée, même module : sort le contenu actuel du `.env` racine (affichage dans
le dashboard et/ou téléchargement du fichier). Aucune écriture vers un service externe.
Confirmation requise (même gate) — exposer en clair l'intégralité des secrets du stack est une
action sensible au même titre que les deux précédentes.

## Montage de la clé USB sur le HP

Règle `udev` sur le HP, basée sur un label de partition fixe (ex. `WORKPLACE-USB`) → montage
automatique sur un chemin fixe (ex. `/mnt/sauvegarde-usb`) dès que la clé est branchée, sans
étape SSH manuelle pour l'utilisateur. Ce chemin est bind-monté en lecture-écriture dans
`core/docker-compose.yml`, au même titre que les volumes déjà montés (`core_data`, etc.).

La sentinelle `.cle-sauvegarde-workplace` (cf. section Sauvegarde) est posée une fois,
manuellement, à la racine de la clé lors de sa préparation initiale — condition nécessaire
pour que `sauvegarde_usb_lancer` accepte d'écrire dessus.

## Erreurs et cas limites

- **Clé non montée** au moment de « sauvegarde »/« restaure » → refus net (sentinelle absente
  ou point de montage vide), message clair, rien n'est écrit ailleurs.
- **Espace insuffisant** → vérifié avant écriture, abandon propre.
- **Conteneur arrêté** au moment de la découverte → absent du manifeste, pas d'échec global.
- **Restauration partielle** (ex. clé débranchée en cours de restauration) → chaque brique est
  restaurée indépendamment (comme documenté comme limite connue du plan RPO d'origine :
  cohérence inter-brique non garantie à la seconde près) ; acceptable pour un cercle privé,
  à revisiter si le multi-tenant devient réel.

## Tests

- Pas de vraie clé USB en environnement de test : les tests de découverte/dump/manifeste
  utilisent un dossier temporaire simulant le point de montage (avec/sans sentinelle, avec/sans
  espace suffisant).
- Preuve bout-en-bout avec une vraie clé faite en LIVE sur le HP (régime habituel du projet :
  coder + tester ici, preuve Docker groupée sur le HP).

## Points ouverts pour la phase de plan

- Mécanisme exact d'enregistrement d'une capacité « noyau » (`core/`) auprès du registre de
  capacités de l'assistant — à vérifier dans le code existant (`core/routers/systeme.py`,
  `core/accord_action.py`, catalogue des capacités) plutôt que supposé ici.
- Emplacement exact du point de montage (`/mnt/sauvegarde-usb` est un nom provisoire) et
  contenu précis de la règle `udev` — à écrire et tester réellement sur le HP.
- Détection Postgres par image vs. par port : choisir le motif le plus robuste en regardant le
  code de découverte une fois écrit contre les 6 bases réelles.
