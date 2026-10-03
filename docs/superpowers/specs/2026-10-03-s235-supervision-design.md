# S235 — Supervision opérationnelle sur le HP

Date : 2026-10-03. Statut : conception validée par l’utilisateur ; supervision implémentée, canal Telegram activé, confirmation de réception en attente.
Source : docs/sprints/S235-S239-infrastructure-supervision-recherche.md.

## État constaté

HP accessible en SSH, dépôt main 4ce4141, Cœur /health OK (41 briques). Aucun conteneur Prometheus/Grafana présent. Backend Oria unhealthy, adaptateur Oria healthy. Disque hôte : 31 % utilisé. Le dépôt Mac contient déjà la stack S225, ses règles et son tableau Grafana.

## Choix

Conserver Prometheus/Grafana S225 et ajouter Uptime Kuma et node_exporter. Kuma porte les notifications Telegram de disponibilité. Prometheus conserve les règles et les métriques métier et collecte CPU, mémoire et disque hôte. Aucun Glances, InfluxDB ou Alertmanager dans ce sprint.

Alternatives : Kuma seul ne couvre pas les métriques métier ; Alertmanager avec blackbox_exporter couvrirait les sondes mais ajoute une chaîne de configuration et remplace l'interface de disponibilité demandée. La combinaison retenue respecte le backlog et sépare métriques et sondes.

## Architecture et configuration

Étendre outils/observabilite avec des images versionnées, volumes persistants, politiques de redémarrage et sondes de santé. Réutiliser le provisionnement Grafana et ajouter une vue hôte. node_exporter lit les ressources hôte sans accès au socket Docker. Limiter les interfaces de gestion au LAN HP ; aucune publication Internet prévue.

Inventorier les URL réelles à partir des manifestes et de la configuration déployée. Kuma surveille le Cœur, les briques et les dépendances critiques ; Oria backend possède une sonde distincte de l'adaptateur. Annoter chaque sonde : processus, dépendance ou métier. Une réponse /health ne prouve pas une opération métier ; les métriques du Cœur complètent cette lecture.

Configurer des sondes à 60 secondes, avec confirmation de panne après plusieurs échecs et notification de rétablissement. Kuma est l'unique émetteur des notifications de disponibilité. Les règles Prometheus restent visibles, sans deuxième émission Telegram. Les seuils CPU/mémoire/disque seront visibles dans Grafana ; leur notification externe n'est pas incluse dans cette première chaîne.

Les identifiants administrateur Grafana/Kuma et le token Telegram restent hors Git et hors sorties de commandes. Demander le canal, son chat_id, un éventuel topic et l'autorisation des messages de test avant tout envoi externe. Si des secrets existent déjà sur le HP, ne pas les afficher et proposer leur réutilisation.

## Déploiement et vérification

Déployer uniquement la supervision, sans mettre à jour ni redémarrer les briques applicatives. Valider Compose et les règles Prometheus avant démarrage. Vérifier les scrapes Cœur/hôte, la source Grafana, les tableaux et les sondes Kuma. Vérifier que le backend Oria apparaît en panne sans masquer le bon état de l'adaptateur.

Créer une cible de test isolée : faire constater son passage disponible → indisponible → disponible ; aucune panne provoquée sur une brique de production. Vérifier messages Telegram panne/rétablissement seulement après configuration autorisée. Redémarrer les services de supervision et vérifier persistance des comptes, sondes et données. Retirer la cible de test après validation.

## Acceptation et limites

Preuves attendues : réponses HTTP réelles, scrapes réussis, métriques consultables dans Grafana, historique Kuma et persistance après redémarrage. La réception Telegram reste un critère ouvert tant que le canal n'est pas configuré et testé. Une supervision hébergée sur le HP ne peut pas notifier sa propre extinction totale : un observateur externe reste hors périmètre. La réparation du backend Oria n'appartient pas à S235.

## Retour arrière

Arrêter uniquement les nouveaux services de supervision et rétablir leurs fichiers précédents. Conserver les volumes pour ne pas supprimer l'historique. Aucun changement des données applicatives.
