# S235 — Résultats de supervision HP

Date : 2026-10-03. Statut : supervision déployée ; validation Telegram en attente du canal.

## Déploiement

Stack ciblée `outils/observabilite` sur `/home/debian/workplace`, sans mise à jour ni arrêt des applications. Images : Prometheus v3.1.0 et Grafana 11.5.1 conservées, Kuma 2.5.5 et node_exporter v1.9.1 ajoutés. Les fichiers précédents sont conservés sous `/home/debian/s235-supervision-backup/` ; le dépôt HP reste main 4ce4141 avec modifications de supervision non commitées. Aucun git pull global.

Interfaces LAN : Grafana http://192.168.1.89:3001, Kuma http://192.168.1.89:3002, Prometheus http://192.168.1.89:9090. node_exporter n'a pas de port publié. Identifiants administrateur générés, stockés uniquement dans `outils/observabilite/.env` sur le HP, permissions 600. Aucun secret ajouté au dépôt ni affiché.

## Preuves obtenues

- Six tests unitaires Python et trois cas de notification JavaScript passent sur Mac et HP : inventaire, santé backend distincte, inclusion des briques `a_tester`, déduplication Cœur/noyau activation explicite de Telegram et nettoyage de la cible même si Kuma échoue.
- `docker compose config --quiet` valide ; `promtool` valide configuration et neuf règles.
- Les trois scrapes Cœur, hôte et Prometheus sont `up` avant redémarrage.
- Grafana provisionne deux tableaux : parc (7 panneaux) et ressources HP (3 panneaux). Les requêtes via son API de datasource rendent les valeurs CPU, mémoire, disque et 17 séries de fraîcheur des tâches. Les panneaux budget, taux d'échec et écarts d'arguments peuvent être vides faute de données/historique récent ; aucune donnée inventée.
- Kuma possède 46 sondes, y compris Forge backend, Keycloak et Oria backend. Deux provisionnements successifs produisent 46 noms uniques.
- Oria backend est DOWN (`ECONNREFUSED`), tandis que l'adaptateur Oria est UP (HTTP 200). Le standard téléphonique conserve son adresse externe LAN déclarée dans le manifeste.
- Panne isolée prouvée avec cadence accélérée à 20 s, deux retries : historique `[1, 2, 2, 0, 1]`, soit UP → PENDING → PENDING → DOWN → UP. Cible et sonde de test retirées, aucun arrêt applicatif.
- Redémarrage ciblé des quatre services effectué ; les quatre healthchecks sont sains. Après redémarrage : trois scrapes UP, données Grafana disponibles, 46 sondes avec les mêmes identifiants et URL, historique Oria conservé (huit battements au moment du contrôle).

Revue de code indépendante : deux défauts corrigés et relus (désactivation effective du canal géré et nettoyage Docker malgré erreur de RPC), aucun défaut important résiduel identifié.

Les scripts `verify-live.py` et `probe-live.py` permettent de reproduire les contrôles sur le HP. Les sondes réelles utilisent 60 s entre deux mesures et deux retries. Kuma SQLite nécessite `UPTIME_KUMA_DB_TYPE=sqlite` ; les transferts macOS doivent exclure les fichiers `._*` et attributs étendus.

## Telegram : préparé, non activé

Réutilisation du token existant autorisée par l'utilisateur. Le canal géré peut être désactivé par reprovisionnement sans supprimer les notifications manuelles. Le helper lit le token du `.env` racine sans le recopier dans Git. Il manque `TELEGRAM_CHAT_ID`, éventuellement `TELEGRAM_TOPIC_ID`, et l'autorisation des messages panne/rétablissement vers cette destination. `TELEGRAM_ENABLED=no` : aucun appel Telegram ni message externe effectué.

Après réception des informations : remplir le fichier privé, activer le canal Kuma, rattacher les sondes et vérifier deux notifications de test avec confirmation de réception. Tant que ces preuves manquent, **S235 n'est pas clôturé** selon les critères du backlog.

## Limites

Les règles métier et ressources sont visibles dans Prometheus/Grafana, sans émission Telegram dans ce sprint. Kuma émet uniquement les transitions de disponibilité ; déduplication des URL et absence de rappels périodiques, sans corrélation globale des pannes en cascade. Une sonde de processus ne prouve pas une opération métier. Une panne totale du HP ne peut pas être notifiée par sa propre supervision. Réparation Oria et sauvegarde des volumes/secrets (S236) hors périmètre.

## Mise à jour Oria — réparation demandée après le sprint

Le backend Oria a ensuite été réparé le 3 octobre : suppression du superviseur `--reload` dans le runtime et réutilisation explicite du réseau HP existant. Voir `S235-oria-reparation.md` pour cause, changement et preuves. Le constat de panne ci-dessus décrit l’état initial du déploiement S235. Telegram reste non activé en attente de l’accord sur la destination.
