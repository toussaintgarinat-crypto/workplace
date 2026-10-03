# Oria — Réparation du backend HP après supervision S235

2026-10-03. Portée : backend Oria uniquement, aucun changement des données ni des images.

## Cause et correction

Au démarrage HP, le worker Uvicorn avait échoué sur une connexion refusée à PgBouncer. La base est revenue disponible, mais le parent `--reload` de développement est resté vivant : Docker ne redémarrait pas le conteneur et le port 8000 ne répondait plus.

L'override Workplace utilise désormais Uvicorn sans `--reload`, en un processus. En cas d'échec d'import, ce processus sort et `restart: unless-stopped` peut appliquer ses retries. Le montage de code est conservé ; une modification de code exige désormais un redémarrage explicite dans ce mode runtime. Le fichier de base garde son mode développement.

Une dérive préalable du réseau a également été constatée : réseau existant `oria_default` en `192.168.240.0/20`, override déclarant `10.99.5.0/24`. Compose tentait de recréer le réseau partagé à la mise à jour. `docker-compose.hp.yml` réutilise explicitement le réseau existant comme externe, sans modifier son sous-réseau. Ce fichier requiert Compose >= 2.24.4 (`!override`), HP vérifié en 5.2.0.

Sur le HP, le `.env` privé inclut :

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker-compose.hp.yml
```

Le réseau `oria_default` doit déjà exister pour cet override HP ; pour une installation vierge, provisionner le réseau avant activation. Les sauvegardes de l'override et du `.env` privé avant correction sont sous `/home/debian/s235-supervision-backup/` (copie de secrets avec droits 600).

## Vérifications

- Avant : backend HTTP inaccessible, worker en échec `OperationalError`; test SQL via PgBouncer déjà redevenu OK.
- Après : `/health` HTTP 200, non dégradé, Redis OK ; `/openapi.json` HTTP 200 ; frontend port 3003 HTTP 200 ; healthcheck Docker `healthy`.
- Requête SQL réelle depuis le backend : table `worlds` lisible (un monde), sans lecture du contenu utilisateur.
- Test isolé avec la même image et le même mode Uvicorn, base volontairement inaccessible, réseau `none`, aucun volume : processus sorti avec code 1 sur connexion refusée. Aucun impact production.
- Redémarrage ciblé du backend vérifié : HTTP 200, conteneur healthy, Cœur disponible et tous les composants Oria healthy. Kuma affiche le backend UP (200 OK) et conserve son historique de panne/rétablissement.
- Aucun `--remove-orphans`, arrêt de base, modification des identifiants ni migration ajoutée.

## Exploitation

```sh
cd /home/debian/workplace/oria-stack/oria
docker compose config --quiet
docker compose up -d --no-deps backend
curl -fsS http://localhost:8000/health
```

Pour revenir à la configuration précédente, restaurer l'override sauvegardé et la valeur antérieure de `COMPOSE_FILE` en conservant les autres secrets. Ne pas tenter de changer le sous-réseau d'un réseau partagé en service.
