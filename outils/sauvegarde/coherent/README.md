# S236 — Exports cohérents et restauration isolée

RPO choisi : 24 h. RTO choisi : 8 h. Un timer toutes les 12 h est préparé pour laisser une marge ; il reste désactivé tant qu’aucune destination n’est configurée et vérifiée.

## Organisation

`inventory-hp.json` est l’inventaire obligatoire du HP du 3 octobre 2026. Il couvre les six serveurs PostgreSQL (toutes leurs bases non templates et rôles), Qdrant et ses alias, etcd, les volumes de fichiers utilisateur, les SQLite dans ces volumes et le dépôt avec ses `.env`, configurations locales et overrides. Les volumes anonymes utiles sont inclus. La découverte Docker compare la réalité à cet inventaire : source manquante, image changée ou montage inconnu font échouer le préflight.

Les caches SearxNG, signatures ClamAV et dépendances node_modules sont explicitement classés reproductibles. L’historique Prometheus est exclu de cette reprise applicative. L’environnement généré `.venv-source-faker` de Connecteurs est exclu ; son code source reste sauvegardé. PostgreSQL/Qdrant/etcd ne sont jamais copiés à chaud comme de simples répertoires.

`backup.py` arrête temporairement les producteurs (Kuma en premier, puis Caddy), laisse PostgreSQL/Qdrant/etcd et les exportateurs de métriques disponibles, et reprend exactement les conteneurs précédemment actifs en ordre inverse. Les sidecars déjà arrêtés restent arrêtés. La cohérence interservices suppose l’absence d’autres écritures directes dans les moteurs pendant cette fenêtre.

SQLite utilise son API de sauvegarde, y compris avec WAL. Si un montage RO empêche SQLite de reconstruire son index SHM, un miroir temporaire privé et stable est utilisé uniquement lorsque les producteurs sont suspendus : DB+WAL si présent, DB seule après checkpoint d’une base en mode WAL. L’export final passe toujours par SQLite Backup API, puis `integrity_check` et des empreintes de schéma/comptages. Les fichiers sont inventoriés et hashés. PostgreSQL utilise des dumps logiques custom, avec rôles et extensions. Qdrant utilise ses snapshots natifs, avec métadonnées, alias et un vecteur réel de contrôle. Etcd utilise son snapshot natif.

Le staging, les générations, les rapports et les logs sont privés (0700/0600). Les valeurs des secrets ne sont pas imprimées. Une génération contient néanmoins les secrets nécessaires à la reconstruction : elle ne doit sortir du HP que par transport chiffré. Les métriques publiques contiennent seulement succès, compteurs et dates.

## Export et contrôle

Depuis le HP, avec Docker accessible au compte Debian :

```sh
python3 outils/sauvegarde/coherent/backup.py preflight
python3 outils/sauvegarde/coherent/backup.py backup
python3 outils/sauvegarde/coherent/backup.py verify --generation /chemin/de/la/generation
python3 outils/sauvegarde/coherent/backup.py status
```

Racine par défaut : `/home/debian/.local/share/workplace-backups`. Elle doit rester hors de toute source sauvegardée. L’export crée une nouvelle génération, ne remplace jamais la précédente et ne publie sous `complete/` qu’après vérification de toutes les sources et reprise des producteurs. Les échecs restent sous `failed/`, exclus du transfert.

Un verrou commun protège exports et transferts. Le journal `recovery.json` est persisté avant chaque arrêt ; un journal restant bloque le prochain export. Après une interruption :

```sh
python3 outils/sauvegarde/coherent/backup.py recover
```

Cette commande vérifie l’identité des conteneurs avant leur reprise. Si une reprise échoue, le journal reste disponible. Ne pas supprimer ce journal pour contourner un échec.

## Disque externe, clé USB, NAS ou serveur

Les profils Duplicati sont dans `../duplicati/`. Chaque destination a sa propre base locale, ses identifiants, sa rétention et son accusé de transfert. Plusieurs profils peuvent être configurés dans un job (par exemple NAS obligatoire et disque amovible facultatif).

Pour un disque/une clé USB ou un NAS déjà monté sur Linux, utiliser un profil `kind: file`. Le support doit être un vrai point de montage, sur un filesystem indépendant des sources/staging, avec une identité `.workplace-s236-target`. Un répertoire vide, même avec une sentinelle, est refusé. L’identité et, si configurés, la source du montage/son UUID sont vérifiés avant et après Duplicati, ainsi que dans le conteneur. Le script ne formate aucun support et ne crée aucun montage de remplacement.

Choisir un identifiant non secret (par exemple UUID), puis écrire **sans retour à la ligne** cette identité dans `.workplace-s236-target` sur le support monté. Renseigner la même valeur dans le profil. La sauvegarde chiffrée sera stockée sous `workplace/<id-du-profil>/` ; les données déjà présentes sur le support ne sont pas supprimées.

Pour un serveur accessible par SFTP, S3 compatible ou WebDAV HTTPS, utiliser `kind: remote`. Le profil contient l’URL sans mot de passe ; les identifiants restent dans un fichier d’environnement privé. SSH impose l’empreinte de clé du serveur ; S3 permet de définir un endpoint compatible et conserve TLS activé. Un serveur sur le LAN convient : la distance géographique est distincte de l’indépendance matérielle. Un NAS ou un disque connecté au HP protège de la panne du disque système ; un support débranché/emporté ou une copie hors site couvre davantage de scénarios.

Une clé débranchée ne peut pas tenir un RPO continu de 24 h. Pour cet objectif, conserver une destination obligatoire disponible en permanence et utiliser l’USB en copie complémentaire, ou brancher/réaliser/vérifier la copie dans ce délai. Sans destination choisie et premier transfert réussi, `rpo_ok` reste faux.

Créer les secrets dans un répertoire privé, avec fichier 0600 appartenant au compte du job. Le fichier accepte `PASSPHRASE`, `AUTH_USERNAME` et `AUTH_PASSWORD` ; la phrase de chiffrement AES est obligatoire. Conserver hors du HP la phrase et les paramètres d’accès à la destination : leur présence dans la sauvegarde chiffrée seule ne permet pas de la déchiffrer après perte du HP.

```sh
python3 outils/sauvegarde/duplicati/transport.py \
  --profile /chemin/prive/profil.json \
  --generation /chemin/de/la/generation \
  --root /home/debian/.local/share/workplace-backups
```

Le transfert ne devient un succès qu’après `backup` puis `test all` avec vérification distante complète. Un avertissement Duplicati est traité comme un échec. Les accusés mentionnent génération et date, sans secrets. Aucune purge locale automatique : conserver les générations jusqu’à vérification et choix d’une politique locale. Duplicati conserve par défaut 30 versions, configurable par profil.

## Planification et interface

`../duplicati/workplace-backup.service` et `.timer` sont prêts pour systemd, mais non installés/activés automatiquement. Le job privé décrit `root`, `inventory` et la liste des chemins des profils. Il vérifie les destinations avant de suspendre les producteurs ; une destination requise absente bloque l’export.

L’interface Duplicati est optionnelle : profil Compose `ui`, accès uniquement `127.0.0.1:8200`, paramètres chiffrés, exports RO et aucun socket Docker. Un job CLI n’est pas automatiquement visible dans l’UI. Ne pas créer une seconde planification UI concurrente avec le timer hôte.

## Restauration de test

```sh
python3 outils/sauvegarde/coherent/restore.py \
  --generation /chemin/de/la/generation \
  --target /chemin/neuf/pour/test
```

La cible doit être nouvelle, hors des sources, sans parent symlink. La génération est vérifiée avant toute création. Tous les conteneurs, volumes et réseaux portent des noms générés `s236-…` et un label dédié ; le réseau est interne, aucun port n’est publié et aucun socket Docker de production n’est monté. Les rôles/bases/extensions/comptages PostgreSQL, les fichiers/SQLite, les points/alias/recherche Qdrant et le snapshot etcd sont contrôlés. Le Cœur est démarré sur les copies pour vérifier `/health` et `/dashboard` sans accès aux intégrations externes.

Le script nettoie ses seules ressources créées ; `--keep` conserve une restauration réussie pour inspection. Le rapport privé donne les ressources exactes et la source active en cas d’échec. Les erreurs natives sont conservées dans des journaux privés 0600, sans afficher les données concernées. Le Cœur doit répondre à `/health` ; le dashboard peut répondre 200 ou rediriger 303 vers l’authentification locale. La sonde ne suit pas le SSO et indique séparément si la page a été rendue. Cette preuve ne vaut pas validation métier de toutes les briques : le rapport expose `full_stack_restored: false`. Le temps de reconstruction de la machine, de récupération distante et des images doit être ajouté au temps d’import pour évaluer le RTO complet.

Pour restaurer depuis Duplicati sans sa base locale initiale, utiliser la destination et la phrase sauvegardées hors HP, `duplicati-cli restore` avec un nouveau `--dbpath` et un **nouveau** `--restore-path`. Vérifier ensuite la génération récupérée avant de lancer la restauration isolée. Ne jamais restaurer vers les chemins d’origine en production pour un test.

Le pilote réel a révélé un index unique incohérent dans Gateway : sa restauration stricte échoue. L’outil ne supprime aucune ligne et n’ignore aucun index automatiquement. Les données ont été récupérées dans un laboratoire dégradé distinct ; la reprise complète reste à valider après traitement de cette incohérence. Voir les [preuves S236](../../../docs/sprints/S236-sauvegardes-resultats.md).

## Supervision et limites

Le timer publie les métriques dans `outils/observabilite/textfile`, monté RO par node-exporter. Prometheus distingue export échoué, transfert échoué/non configuré, copie indépendante plus ancienne que 24 h et métriques absentes. Ces règles ne créent pas de nouveau canal de notification externe.

S233 USB demeure une capacité historique distincte ; les exports cohérents S236 passent par cet outillage et Duplicati. L’historique TSDB de Prometheus est exclu ; sa configuration est couverte. Le présent périmètre sauvegarde l’application et ses configurations montées, pas une image Proxmox complète ni les clés personnelles SSH de l’hôte. La reconstruction de l’hôte et son réseau relève de S237 ; les paramètres hôte supplémentaires nécessaires doivent être inventoriés avant une validation de reprise complète.

Documentation primaire consultée : [snapshots Qdrant](https://qdrant.tech/documentation/operations/snapshots/), [Duplicati Docker](https://docs.duplicati.com/platform-specific-guides/using-duplicati-from-docker), [CLI Duplicati](https://docs.duplicati.com/duplicati-programs/command-line-interface-cli), [SFTP](https://docs.duplicati.com/backup-destinations/standard-based-destinations/sftp-ssh-destination), [version stable 2.4](https://github.com/duplicati/duplicati/releases/tag/v2.4.0.0_stable_2026-09-03).
