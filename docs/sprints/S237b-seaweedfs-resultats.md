# S237b — MinIO remplacé par SeaweedFS : résultats

Date : 2026-10-04. Branche `sprint/s237-ansible`.

## Pourquoi

L'image `minio/minio:RELEASE.2025-09-07T16-13-09Z` n'est plus publiée (Docker Hub et Quay refusent l'accès). Un hôte neuf ne pouvait donc pas démarrer Oria sans séquestre d'image (constat S237). Le S3 est conservé volontairement pour un usage futur. MinIO ne contenait aucun bucket : seulement `.minio.sys`, 104 Ko, revérifié juste avant la bascule. Aucune migration de données n'était donc nécessaire.

## Configuration retenue

- Image : `chrislusf/seaweedfs:4.48@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`, publiée le 2026-09-28, multi-architecture.
- Mode `server -s3` en un seul conteneur, volume `seaweedfs_data`, API S3 sur le port hôte 9106 et santé sur `/healthz`.
- Clés `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` obligatoires dans `oria-stack/oria/.env` (`:?`). Elles sont passées en `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` et deviennent l'identité administrateur.

Points vérifiés sur l'image réelle avant de figer les options :

| Constat | Option |
|---|---|
| Les API master/volume/filer sont sans authentification (le filer annonce « IAM gRPC unauthenticated »). | `-ip=127.0.0.1 -ip.bind=127.0.0.1` : boucle locale du conteneur uniquement |
| Le S3 doit rester joignable. | `-s3.ip.bind=0.0.0.0` |
| Le catalogue Iceberg REST (8181) et le serveur Lance (9101) démarrent par défaut sur 0.0.0.0 ; Iceberg répond `200` sans authentification. | `-s3.port.iceberg=0 -s3.port.lance=0` |
| L'API IAM embarquée n'est pas utilisée. | `-s3.iam=false` |
| **Sans clés, le S3 accepte les requêtes anonymes** (liste et création de bucket en `200`). | Clés obligatoires partout (`:?`), y compris la cible de développement |

Mêmes changements pour la Forge autonome (`docker-compose.standalone.yml`) et pour la cible S3 de développement de Litestream/WAL-G (`outils/sauvegarde`, endpoint `http://seaweedfs:8333`, bucket créé par un conteneur `curl` SigV4 qui accepte le `409`).

## Déploiement HP (2026-10-04, ~23:30)

1. Les fichiers HP à remplacer étaient identiques à la version d'avant changement (empreintes comparées). Ils sont sauvegardés dans `~/s237b-deploy-backup/before.tgz`, puis remplacés **en place** (montages fichier de Kuma).
2. Clés S3 générées sur le HP, jamais affichées ; le `.env` est resté en 600.
3. `oria-minio-1` est arrêté et supprimé. Volume et image conservés à ce stade, supprimés ensuite sur accord (voir plus bas).
4. `seaweedfs` est démarré seul (`--no-deps`) : sain en ~8 s, `Config.Image` identique à la chaîne de l'inventaire S236.
5. Le backend Oria a été redémarré (alerte renommée `ObjectStorageDown`).
6. Kuma : 47 sondes, dont « Dépendance — Oria S3 (SeaweedFS) », UP (200), avec Telegram rattaché.
7. Le timer S236 lit sa **propre copie** de l'inventaire (`~/s236-tools/coherent/inventory-hp.json`). Elle a été mise à jour, et `backup.py preflight` passe (76 conteneurs).

Preuves sur la production :

- Requête anonyme : `403`. Mauvaise clé : `403`.
- Bucket et objet : création `200`, écriture `200`, relecture identique (`cmp`), suppression `204` puis `204`. Aucun bucket restant.
- Depuis le réseau `oria_default`, seul 8333 répond (`403` sans signature). 8888, 9333, 8080, 18888, 19333, 8181 et 9101 sont injoignables.
- 71/71 conteneurs en cours d'exécution sont sains.

## Relecture indépendante

Un autre agent a relu en lecture seule l'outillage S237 du 2026-10-04 et ce changement. Résultat : 0 Critical, 5 Important, 13 Minor. Correctifs appliqués :

| # | Défaut | Suite |
|---|---|---|
| I1 | Une mise à jour qui retire un service échouait toujours (`runtime service set drift`), faute de `--remove-orphans`. | Corrigé, test « service retiré » ajouté (il échouait avant le correctif) |
| I2 | La génération de l'époque MinIO ferait échouer la restauration sur la VM 106. | Ordre imposé dans le plan : nouvelle génération après la bascule, puis purge de la cible ou VM neuve |
| I3 | Les contrôles d'isolation comptaient « connexion refusée » comme un succès. | Seuls EPERM, délai dépassé, ENETUNREACH, EHOSTUNREACH et EADDRNOTAVAIL sont acceptés ; le port 22 est aussi sondé ; tests ajoutés |
| I4 | Le S3 de développement démarrait en anonyme si les clés étaient vides. | Confirmé sur l'image, puis corrigé (`:?`) |
| I5 | La sauvegarde serait refusée pendant la bascule. | Pris en compte dans la procédure : conteneur supprimé, inventaire en service mis à jour, preflight vérifié |
| m1 | L'hyperviseur Proxmox n'était pas refusé par la garde. | `192.168.1.222` est refusé, et l'existence de `/etc/pve` interdit la cible |
| m6 | Les identifiants apparaissaient dans la commande du conteneur d'initialisation de développement. | Passés par l'environnement plutôt que par l'entrypoint (ils restent visibles par `docker inspect`, comme pour tout service) |
| m10 | La phrase de passe de production restait sur la VM gardée. | Installation et récupération dans un `block`, `recovery.env` supprimé dans son `always` |
| m11 | La reprise Qdrant recréait des alias existants. | Seuls les alias manquants sont créés |
| m13 | Le catalogue « observé » avait été édité à la main. | Mentionné dans le README Ansible |

Différés : sondes HTTP sans contrôle de contenu (m2), relais qui ignore `host_ip` (m3), délais du relais pour WebSocket/SSE (m4), garde-fous de `stage_backup.sh` (m9), rôle `s237_bootstrap_*` laissé dans les PostgreSQL restaurés (m12), et le même schéma d'alias Qdrant dans `outils/sauvegarde/coherent/restore.py` (S236, hors périmètre). La sonde S3 prouve un aller-retour, pas la restauration de données S3 : il n'y a aucun bucket à restaurer aujourd'hui (m5).

Seconde relecture des correctifs : 5/5 OK, aucun nouveau défaut Important ou Critical ; ses deux remarques mineures (identifiants installés hors du `block`, commentaire m6) sont corrigées. Elle signale que le contrôle d'isolation de l'hôte sonde maintenant 2 ports par adresse, ce qui peut allonger le passage d'isolation (403 s en S237) : à mesurer au rejeu.

Tests : Ansible 46, coherent 68, duplicati 17, observabilité 6, reconstruction 8 — tous verts (pytest).

## Reste

- Rejeu de la reconstruction sur la VM 106 sans séquestre : **mis en attente** (décision utilisateur, pas pour tout de suite), l'hôte Proxmox est toujours à 32 Go et la VM 106 demande 12 Go en plus de 103 (24 Go) et 104 (4 Go).

## Nettoyage MinIO (2026-10-04, ~23:50, sur accord)

Après contrôle (SeaweedFS sain, aucun conteneur sur le volume, preflight S236 passé sans MinIO), ont été supprimés : le volume `oria_minio_data` (132 Ko, métadonnées internes MinIO seulement), l'image `minio/minio:RELEASE.2025-09-07T16-13-09Z` (241 Mo) sur le HP, et l'archive du séquestre privé S237 sur le contrôleur (avec sa ligne de `SHA256SUMS`). Les générations S236 antérieures contiennent toujours l'ancien volume.
