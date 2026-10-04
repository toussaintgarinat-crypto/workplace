# Duplicati S236

Le transport utilise l’image officielle stable 2.4.0.0, épinglée par digest. Il reçoit uniquement une génération S236 complète, vérifiée et montée en lecture seule. La base locale et les logs sont privés et séparés par destination. AES est obligatoire ; un transfert n’est acquitté qu’après une vérification distante complète.

Trois exemples de profils sont fournis : `profile-removable.example.json` pour disque dur externe/clé USB, `profile-nas.example.json` pour NAS monté, `profile-remote.example.json` pour serveur SFTP/S3 compatible/WebDAV HTTPS. Les chemins et identités des exemples doivent être remplacés par ceux du support réellement choisi. Ils ne sont pas des destinations actives.

Un profil file exige un montage réel et une sentinelle `.workplace-s236-target` contenant exactement l’identité du profil, sans retour à la ligne. Un montage sur le même filesystem que le staging ou le disque système est refusé. Une cible NAS peut être locale au LAN ; une clé/disque peut être débranché et emporté après vérification. Le transport ne formate, ne partitionne et ne monte aucun disque. Le montage USB persistant spécifique au HP est préparé séparément par le [runbook USB](USB-SCHEDULE.md).

Un profil remote ne contient pas de mot de passe dans l’URL. Les options non secrètes acceptées sont limitées aux réglages de backend nécessaires : empreinte SSH et paramètres S3 compatible ; TLS ne peut pas être désactivé.

Les secrets du transport restent dans un répertoire 0700, fichier 0600 appartenant au compte du job :

```text
PASSPHRASE=<phrase-de-chiffrement>
AUTH_USERNAME=<identifiant-si-requis>
AUTH_PASSWORD=<mot-de-passe-si-requis>
```

Ces valeurs ne sont jamais passées en clair sur la ligne de commande ni imprimées. Conserver hors du HP une copie de la phrase et des paramètres d’accès à la destination ; ne pas dépendre de la base locale Duplicati pour la récupération.

Pour le job hôte, créer un fichier JSON privé :

```json
{
  "root": "/home/debian/.local/share/workplace-backups",
  "inventory": "/home/debian/workplace/outils/sauvegarde/coherent/inventory-hp.json",
  "profiles": ["/home/debian/.config/workplace-backups/profil.json"]
}
```

Les profils sont obligatoires par défaut (`required: true`). Une destination obligatoire indisponible bloque le job avant toute interruption applicative. La cadence préparée est toutes les 12 h ; les unités `workplace-backup.service` et `workplace-backup.timer` ne sont pas activées automatiquement. Le RPO se calcule à partir du début de la génération vérifiée, et non de l’heure du transfert. Une génération ancienne retransférée aujourd’hui reste ancienne ; pour plusieurs destinations obligatoires, le point source le plus ancien est retenu. Le statut est publié dans `outils/observabilite/textfile` pour node-exporter.

L’UI optionnelle est liée à localhost et ne possède ni socket Docker ni accès aux données actives. Définir `DUPLICATI_UID` et `DUPLICATI_GID` (propriétaire des fichiers privés), `DUPLICATI_UI_ENV` (fichier privé contenant `SETTINGS_ENCRYPTION_KEY` et `DUPLICATI__WEBSERVICE_PASSWORD`), `DUPLICATI_PRIVATE_DATA` (0700) et `WORKPLACE_COMPLETE` (répertoire complete des exports). L’utilisateur du conteneur doit correspondre au propriétaire de la base privée. Vérifier avec `docker compose --profile ui config --quiet`, puis démarrer seulement si l’UI est souhaitée. Ne pas activer un second ordonnanceur UI en parallèle du timer.

Détails de sauvegarde et de restauration : [guide S236](../coherent/README.md). Les clés d’UI, de chiffrement des paramètres et de chiffrement des sauvegardes ont des rôles différents : conserver les éléments nécessaires à la récupération hors du HP.
