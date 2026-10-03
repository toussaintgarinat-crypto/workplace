# Supervision Workplace — S225 + S235

Prometheus/Grafana : métriques métier du Cœur et ressources hôte. Kuma : disponibilité et notifications Telegram. Une réponse HTTP de santé ne prouve pas une opération métier ; les métriques de fraîcheur et d'échec du Cœur restent nécessaires.

## Déploiement HP

Depuis `/home/debian/workplace/outils/observabilite` :

```sh
python3 inventory.py > monitors.json
# Créer .env depuis .env.example, droits 600, mots de passe forts.
docker compose --env-file .env config --quiet
docker compose --env-file .env run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
docker compose --env-file .env up -d
```

Le fichier `monitors.json` versionné est un instantané ; le régénérer depuis les manifestes de la version réellement déployée. Les statuts `actif` et `a_tester` sont inclus. Les URL identiques sont dédupliquées (Cœur/noyau). Les adresses LAN des services externes sont conservées : une cible absente doit rester visible. Oria/Forge backend et Keycloak sont surveillés séparément.

Kuma embarque le client Socket.IO utilisé par `kuma-bootstrap.cjs`. Fournir via stdin JSON `username`, `password`, et `setup:true` seulement à la première initialisation. Relancer sans `setup` pour mettre à jour les sondes sans doublons. Exemple (secret lu depuis `.env`, jamais argument de processus) :

```sh
python3 kuma-config.py | docker exec -i workplace_uptime_kuma node /app/s235-bootstrap.cjs
```

La première initialisation utilise `python3 kuma-config.py --setup`. Le fichier `.env` ne change pas un mot de passe déjà stocké en base : conserver ses identifiants initiaux.

## Accès

- Grafana : http://192.168.1.89:3001
- Kuma : http://192.168.1.89:3002
- Prometheus : http://192.168.1.89:9090

Interfaces liées à `SUPERVISION_BIND_IP` (loopback par défaut, LAN HP dans `.env`). node_exporter est accessible seulement dans le réseau Compose. Aucun socket Docker monté. `/` est monté en lecture seule pour CPU, mémoire et disque réels ; l'exportateur n'utilise pas le réseau hôte, ses métriques réseau ne servent pas à ce tableau. Volumes nommés persistants, redémarrage `unless-stopped`.

## Telegram

Kuma est l'unique émetteur des alertes de disponibilité. Sonde toutes les 60 s, deux retries de 60 s, pas de renvoi périodique. Les règles Prometheus sont visibles dans Grafana/Prometheus et ne sont pas envoyées vers Telegram dans ce sprint. Cette réduction des doublons n'est pas une corrélation automatique des pannes en cascade : plusieurs services réellement en panne produisent plusieurs alertes.

`kuma-config.py` réutilise le `TELEGRAM_BOT_TOKEN` du `.env` racine si absent du `.env` de supervision. Fournir `TELEGRAM_CHAT_ID`, éventuellement `TELEGRAM_TOPIC_ID`, puis `TELEGRAM_ENABLED=yes` **seulement après autorisation du canal et des envois**. Reprovisionner les sondes. Le provisionnement avec `no` retire le canal Telegram S235 des sondes gérées, tout en conservant les notifications manuelles. Pour désactiver après activation : mettre `no` **et relancer le provisionnement** ; modifier le fichier seul ne change pas Kuma. Le provisionnement ne déclenche pas de message de test explicite, mais les transitions des sondes activées peuvent notifier immédiatement.

Tester avec une cible HTTP isolée ; vérifier panne puis rétablissement dans Kuma et Telegram, puis retirer la sonde de test. Une réponse Telegram réussie prouve l'acceptation par l'API ; la réception doit être confirmée par le destinataire.

## Vérifications et retour arrière

```sh
python3 -m unittest discover -s . -p 'test_*.py'
docker compose --env-file .env ps
curl -fsS http://192.168.1.89:9090/api/v1/targets
curl -fsS http://192.168.1.89:3001/api/health
curl -fsS http://192.168.1.89:3002/
docker compose --env-file .env restart
```

Après redémarrage, attendre une cadence de collecte (60 s) avant de vérifier les scrapes Cœur/hôte, tableaux Grafana et conservation des sondes/comptes Kuma. Pour retour arrière : `docker compose --env-file .env down` (sans `-v`) puis restaurer la sauvegarde des fichiers de supervision. Ne pas supprimer les volumes ni toucher aux projets applicatifs.

Kuma et Prometheus sur le HP ne peuvent pas signaler son extinction totale. Un observateur externe reste nécessaire pour cette garantie. Les sauvegardes des volumes et secrets sont à intégrer à S236.

Contrôles reproductibles sur le HP : `python3 verify-live.py` vérifie les données fournies aux panneaux par l'API Grafana authentifiée ; `python3 probe-live.py` crée une cible isolée, prouve UP → PENDING → DOWN → UP puis la nettoie. Ce dernier test accélère la cadence à 20 s et garde les deux retries ; aucune notification externe n'est activée par ce test par défaut. Après accord et configuration du canal, `python3 probe-live.py --telegram` vérifie les transitions avec notification ; la réception des messages doit être confirmée par le destinataire. Il utilise l'image applicative `core-core:latest` déjà présente comme runtime Python, sans démarrer l'application ni monter ses données.

Pour transférer depuis macOS, exclure métadonnées et caches :

```sh
tar --disable-copyfile --no-xattrs --exclude='__pycache__' -czf /tmp/s235-supervision.tgz -C outils observabilite
```

Les fichiers `._*` ne sont pas des configurations ; Grafana les rejette s'ils arrivent dans le provisioning.
