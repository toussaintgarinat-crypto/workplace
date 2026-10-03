# S235 → S239 — Infrastructure, supervision et recherche

Date : 2026-10-03. Statut : S235 terminé et validé ; S236 à S239 restent au backlog.

## État de départ

La numérotation explicite retrouvée atteint S234 (durcissement du gate Forge et références aux couches de configuration tenant). Les travaux World Engine et pont Studio plus récents utilisent des noms et des lettres de sprint plutôt que de nouveaux numéros Sxxx. S235 à S239 sont libres dans le dépôt inspecté.

S225 dispose du code Prometheus/Grafana, mais aucun conteneur de cette supervision n'était présent sur le HP lors de l'inspection du 3 octobre. S233 a introduit la sauvegarde USB ; la couverture et la restauration complète restent à éprouver. S226 est toujours décrit comme conditionnel dans son backlog. Ces constats ne constituent pas une clôture globale des anciens sprints.

HP : dépôt main au commit 4ce4141 du 26 août ; dépôt Mac au commit 0db3857 du 27 août. Le backend Oria est unhealthy et ne répond pas sur le port 8000, malgré une sonde positive de l'adaptateur Oria. Le répertoire /mnt/sauvegarde-usb est vide, sans sentinelle ; aucun support de sauvegarde utilisable n'est établi par cette inspection.

## S235 — Supervision opérationnelle et alertes de disponibilité

Statut : terminé le 2026-10-03, déployé et testé sur le HP ; réception Telegram panne/rétablissement confirmée par l’utilisateur. Preuves : [résultats S235](S235-supervision-resultats.md).

Objectif : rendre visibles les pannes réelles et les dégradations métier.

- Déployer et vérifier Prometheus/Grafana existants, sans ajouter InfluxDB.
- Ajouter Uptime Kuma pour la disponibilité, en utilisant les URL de santé des manifestes et les dépendances critiques, notamment le backend Oria.
- Raccorder les notifications à un canal choisi et configurer leur regroupement pour éviter les doublons.
- Surveiller les ressources hôte ; choisir Glances ou un exportateur Prometheus selon le besoin, sans installer les deux par défaut.
- Distinguer processus vivant, dépendances disponibles et fonctionnement métier.

Acceptation : indisponibilité simulée sur une cible isolée détectée ; notification de panne et de rétablissement reçue ; métriques visibles dans Grafana ; redémarrage des services de supervision vérifié. Aucun envoi externe avant configuration et autorisation du canal.

## S236 — Sauvegardes cohérentes et restauration complète

Objectif : pouvoir reconstruire Workplace avec ses données.

- Produire des sauvegardes SQLite cohérentes plutôt que copier les fichiers actifs ; conserver les dumps PostgreSQL.
- Couvrir Qdrant, les fichiers utilisateur et les configurations/secrets nécessaires, avec inventaire explicite des sources attendues.
- Conserver plusieurs générations, vérifier leur intégrité et signaler les sauvegardes partielles.
- Préparer Duplicati pour la planification, le chiffrement et la rétention des exports cohérents ; définir une destination indépendante du disque du HP.
- Établir les objectifs de perte de données et de temps de restauration avant de fixer la cadence.

Acceptation : restauration sur une installation isolée, contrôles de bases et de fichiers, recherche Qdrant après restauration ; alerte en cas de destination absente ou de source manquante. Aucune restauration de test sur la production.

## S237 — Provisionnement et déploiement reproductibles avec Ansible

Objectif : transformer les procédures existantes en installation répétable.

- Créer inventory, playbooks et rôles pour les prérequis Debian/Docker, les réseaux et les multiples projets Compose.
- Séparer provisionnement hôte et déploiement applicatif ; protéger les secrets et leurs sorties.
- Déployer une version Git explicite et construire les briques séquentiellement dans l'ordre des dépendances.
- Vérifier les services après déploiement ; documenter le retour arrière applicatif et ses limites pour les migrations de données.
- Inclure la supervision S235 et la préparation des sauvegardes S236.

Acceptation : installation sur une cible vierge, second passage idempotent, contrôles de santé ; mise à jour ciblée et retour arrière éprouvés sur une cible isolée.

## S238 — Recherche Mémoire avec repli lexical indépendant

Objectif : retrouver les références exactes même sans embeddings disponibles.

- Séparer récupération lexicale et récupération vectorielle dans Mémoire PostgreSQL/pgvector.
- Inclure les souvenirs sans embedding dans la branche lexicale, en conservant les droits et les filtres.
- Définir le comportement des références exactes et fusionner les résultats sans addition arbitraire de scores incompatibles.
- Comparer les résultats sur un jeu de requêtes représentatif avant/après.

Acceptation : références, noms et termes métier retrouvés ; panne de l'embedder laissant une recherche lexicale utilisable ; absence de fuite entre espaces/utilisateurs ; mesure de pertinence et de latence.

## S239 — Recherche documentaire hybride Meilisearch + Qdrant

Objectif : une recherche interne rapide sur les documents, avant extension aux messages.

- Ajouter Meilisearch comme service autonome, avec contrat Workplace et version d'image épinglée.
- Définir le corpus documentaire, les identifiants document/fragments et la synchronisation des créations, modifications, suppressions et changements de droits.
- Implémenter un client Python, des filtres/facettes et une fusion RRF avec Qdrant ; définir explicitement la priorité des références exactes.
- Appliquer les autorisations dans les deux moteurs avant fusion ; prévoir un fonctionnement dégradé et une réindexation reprenable.
- Intégrer le nouveau service à la supervision, aux sauvegardes et au déploiement.

Acceptation : recherche exacte, sémantique et avec faute de frappe mesurée ; suppression et retrait d'accès propagés ; aucune fuite inter-tenant ; panne d'un moteur signalée avec résultats dégradés ; reconstruction de l'index vérifiée.

## Ordre

S235 → S236 → S237 → S238 → S239. S238 peut être réalisé indépendamment des travaux d'infrastructure. Les spécifications et plans détaillés seront rédigés au démarrage de chaque sprint. Les messages et wikis sont exclus du premier périmètre S239.
