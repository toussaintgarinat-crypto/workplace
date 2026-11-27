# S247 — Spike : rétention des images de retour arrière du registre Forgejo (2026-11-26)

Méthode : lecture seule avec le jeton `FORGEJO_REGISTRY_TOKEN` (jamais affiché) ; un seul `DELETE` d'essai sur un paquet inexistant pour tester les droits ; rien n'a été supprimé.

## Constats
- `GET /api/v1/packages/wp-admin?type=container` répond 200 : **9 versions** pour 2 paquets (`calendrier-familial-<suffixe>` : 6 + 3 versions), tags `latest` et `v1…v7`. Le paquet est nommé d'après l'`appName` Dokploy de l'application : le **jumeau** du reset créera donc ses propres paquets (un par emplacement).
- `DELETE /api/v1/packages/{owner}/container/{nom}/{version}` : avec `FORGEJO_REGISTRY_TOKEN` la réponse sur un paquet inexistant est **404** (authentifié, droit `write:package` présent) ; avec `FORGEJO_TOKEN` : **403** (« token does not have … write:package »). Le jeton « registre » suffit donc pour la rétention ; l'autre ne doit pas être utilisé.
- Disque VM 100 : 6,9 Go utilisés sur 59 Go (50 Go libres). La taille exacte par version n'a pas pu être lue (l'API `files` ne renvoie pas de champ `size` utilisable) ; les couches sont partagées entre versions, donc le coût marginal d'une version est faible tant que le code ne change pas beaucoup.

## Décision proposée (à implémenter en 2c, pas en 2b)
- **Où** : script de l'exécuteur sur la VM 100 + timer systemd (même mécanique que `sauvegarde_forgejo.py`), jeton de registre dans `/etc/executeur-restauration/env` (root 0600, posé à la main).
- **Combien** : garder les **10 dernières versions `vN` par paquet** ET toute version encore référencée par un déploiement de rollback Dokploy de l'application (à lire via la brique : `application.one → deployments[].rollback`), jamais `latest`.
- **Garde-fous** : ne toucher qu'aux paquets `container` du propriétaire `wp-admin` dont le nom correspond à un `appName` connu de Dokploy ; mode « à blanc » (liste ce qui serait supprimé) activé par défaut tant que l'utilisateur n'a pas validé ; journal des suppressions ; refuser si moins de 3 versions resteraient.
- **Test** : sur le paquet du témoin, créer >10 versions par redéploiements, vérifier que les 10 dernières et les versions de rollback restent.

## Réalisation (2026-11-27, S247 2c)
- Script `outils/executeur-restauration/retention_registre.py` (+ 11 tests) ; rôle Ansible : service + timer `forgejo-retention` (04:15), **inactif** tant que `executeur_retention_active` n'est pas vrai.
- Règle livrée : garder les **10 dernières versions** de chaque paquet dont le nom commence par un préfixe autorisé (frontière `-`), jamais `latest`, refus si GARDER < 3, **à blanc par défaut** (`EXECUTEUR_RETENTION_APPLIQUER=1` pour supprimer), échec de suppression ⇒ code 2, listage en échec ⇒ rien supprimé.
- **Écart au spike** : la garde « versions référencées par un rollback Dokploy » n'est PAS implémentée (la VM 100 n'a pas de clé Dokploy) ; elle est remplacée par « 10 dernières versions », qui couvre les retours arrière récents.
- Live VM 100 : jeton + préfixe posés dans `/etc/executeur-restauration/env` (0600) ; script lancé à blanc sous le confinement de l'unité : lecture OK, 0 suppression (9 versions) ; simulation GARDER=3 : sélectionne `calendrier-familial-sq5rzh:v1` et `:v2`. Le `DELETE` réel avec cette logique n'a pas encore été exercé (il le sera au premier dépassement de 10 versions).
