# S236 — Sauvegardes cohérentes et restauration isolée

Date : 2026-10-03. Statut : conception validée par l’utilisateur ; implémentation et pilote en cours.

## Constats vérifiés

HP joignable, Cœur /health 200, conteneurs actifs healthy. Inventaire Docker : 76 conteneurs, y compris les sidecars arrêtés. Six serveurs PostgreSQL : Mémoire, Gateway, Keycloak, Oria/Patroni, PeerTube, Forge. Qdrant Forge : v1.12.4. S233 copie les SQLite actifs, ignore les sources indisponibles, ne couvre ni Qdrant ni secrets et écrase la génération précédente.

## Choix proposé

Recommandation : orchestrateur hôte produisant des générations immuables, puis Duplicati transférant uniquement les générations validées vers une destination indépendante du HP. Séparer cohérence applicative et transport permet de vérifier les exports sans confier à Duplicati les fichiers de bases actifs.

Alternatives : étendre seulement le module USB (insuffisant pour rétention et transfert indépendant) ; snapshots de VM (rapides, mais dépendants de l’infrastructure et insuffisants seuls pour la portabilité et la cohérence applicative).

## Inventaire obligatoire

Un inventaire versionné associe chaque source attendue à son propriétaire, son type, son chemin ou volume, son export et son contrôle de restauration. Découverte Docker pour détecter les écarts, jamais pour rendre silencieusement facultative une source arrêtée.

Inclure toutes les bases SQLite identifiées dans les volumes, y compris Cœur, Grafana et Kuma ; toutes les bases non template des six serveurs PostgreSQL et leurs rôles ; toutes les collections Qdrant et leurs alias ; tous les fichiers utilisateur des volumes /data, exports, clips, notes et uploads. Inclure MinIO Oria, médias/clefs Dendrite, fichiers PeerTube, fichiers IDE utiles et modèles voix locaux. Classer explicitement caches, node_modules et métriques historiques comme reproductibles ou optionnels ; ne pas exclure un volume anonyme sans inspection.

Inclure configurations Compose et overrides, fichiers non suivis nécessaires, .env racine et locaux, configurations Gateway, Keycloak, Patroni, Matrix, LiveKit, Caddy et supervision, clés applicatives et certificats. Enregistrer commit, images/digests, extensions PostgreSQL, propriétaire et permissions. Ne jamais imprimer les secrets dans les logs ou le manifeste public.

## Cohérence et publication

SQLite : API de sauvegarde SQLite, avec timeout et integrity_check, jamais copie du .db actif seul. PostgreSQL : pg_dump logique par base, rôles nécessaires protégés et extensions inventoriées. Qdrant : snapshots via API, export des alias et métadonnées de collections.

Ces exports assurent une cohérence par moteur, pas une transaction globale. Pour une génération cohérente entre bases et fichiers liés, suspendre les producteurs applicatifs et tâches de fond inventoriés pendant la fenêtre d’export ; laisser les moteurs accessibles aux outils natifs. Reprendre les producteurs dans un finally et signaler toute reprise échouée. Mesurer cette fenêtre lors du pilote avant activation planifiée ; aucun arrêt global implicite.

Répertoire privé mode 0700, fichiers sensibles 0600. Écriture dans une génération temporaire, manifeste avec dates, résultats par source et SHA-256 ; publication atomique uniquement après succès de toutes les sources obligatoires et vérification. Conserver les échecs comme diagnostics privés, exclus du transfert. Verrou contre exécutions concurrentes. Rétention locale n’effaçant jamais la dernière génération valide avant confirmation du transfert distant.

## Duplicati

Préparer un Compose séparé, image stable épinglée après vérification de la documentation officielle, interface liée à localhost, exports montés en lecture seule et configuration persistante protégée. Chiffrement obligatoire ; phrase secrète et procédure de récupération détenues hors du HP. Sauvegarder les paramètres permettant de reconstruire le job sans dépendre de la base locale Duplicati. Pré-exécution : génération complète disponible ; post-exécution : vérifier résultat du transfert. La planification et la rétention seront fixées selon destination, RPO et RTO fournis par l’utilisateur ; aucune valeur inventée ni transfert externe avant destination choisie.

## Erreurs et supervision

Source obligatoire absente, collection manquante, destination inaccessible, espace insuffisant, export corrompu, transfert échoué ou génération trop ancienne : statut échec et métriques lisibles par la supervision S235. Tester ces cas sans provoquer de panne de production. Un succès d’export local ne constitue pas un succès de sauvegarde indépendante. Ne pas envoyer de nouvelle notification externe sans instruction explicite.

## Restauration isolée et acceptation

Créer des conteneurs, réseaux et volumes S236 distincts, sans proxy_net, sans montage de production, sans ports publics et sans intégrations externes actives. Vérifier SHA-256 avant extraction, refuser chemins traversants et cibles de production. Restaurer SQLite et contrôler integrity_check et contenu ; PostgreSQL avec extensions adaptées, rôles et contrôles de tables/comptages ; Qdrant avec collections, alias, nombre de points et recherche sur un vecteur réel. Comparer fichiers et permissions, vérifier présence des configurations/secrets sans les afficher.

Prouver le chiffrement et un téléchargement/restauration depuis Duplicati dès que la destination est disponible. Rapporter séparément temps des exports, du transfert et de restauration ; le RTO complet inclut reconstruction du code, images et services, pas seulement import des bases. Une restauration de moteurs dans des conteneurs isolés est une preuve partielle ; clôture seulement après démarrage isolé de Workplace et contrôles métier représentatifs. Aucun test de restauration sur la production.

## Décisions attendues

Conception validée par l’utilisateur. RPO retenu : 24 h ; RTO retenu : 8 h. Exigence complémentaire validée : disque dur externe ou clé USB, en plus d’un NAS ou serveur local/distant ; profils indépendants pour ces destinations. Destination retenue : clé USB. Support identifié : PHILIPS, partition exFAT UUID 6A01-B378, rattachée à chaud à la VM 103 ; montage en attente d’authentification administrateur confirmée ; aucun transfert indépendant ni timer activé. Cadence préparée : 12 h pour conserver une marge sous le RPO. La disponibilité des images, outils natifs, accès aux volumes et corpus Qdrant sera vérifiée pendant le préflight ; toute limite sera documentée plutôt que déclarée comme preuve.

## Précisions issues du pilote

Les sources applicatives réellement montées et l’environnement privé de supervision sont couverts. Les métriques S236 passent par un répertoire textfile public dédié ; aucun nouveau canal externe n’est ajouté. Les paramètres hôte Proxmox/réseau et clés personnelles SSH ne constituent pas une image de reprise de l’hôte et restent hors de cette preuve applicative (S237).

SQLite peut laisser WAL sans SHM à l’arrêt. Si l’ouverture sur montage RO échoue dans ce cas, un miroir privé DB+WAL dont la stabilité est vérifiée est autorisé uniquement après suspension des producteurs ; l’export final utilise toujours SQLite Backup API et vérification d’intégrité, jamais immutable qui ignorerait WAL.

Le test applicatif démarre le Cœur sur les copies sans egress, socket Docker ni ports publics, en plus des contrôles des moteurs. Ce contrôle ne remplace pas une validation métier de toutes les briques ; le rapport conserve explicitement full_stack_restored=false.
