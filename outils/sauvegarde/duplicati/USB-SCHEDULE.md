# Planification USB S236 sur le HP

Ce paquet prépare le disque exFAT **déjà utilisé**, UUID `6A01-B378`, sur `/mnt/workplace-backup`. Il ne formate rien, ne supprime aucune donnée et ne contient aucune clé. L’installateur root prépare le montage persistant et les unités ; il ne démarre ni n’active le timer.

Le pilote HP est installé et le timer activé depuis le 4 octobre 2026, après restauration isolée et premier job systemd réussis. Voir les [preuves S236](../../../docs/sprints/S236-sauvegardes-resultats.md). Les étapes ci-dessous décrivent l’installation et l’activation sur une cible préparée.

## Fichiers de fonctionnement

Les scripts du pilote sont installés sous `/home/debian/s236-tools/coherent` et `/home/debian/s236-tools/duplicati`, indépendamment du checkout de production. Le service utilise le job privé `/home/debian/.config/workplace-backups/usb-job.json`, son inventaire S236 et le profil `/home/debian/.config/workplace-backups/usb-profile.json`. Ce profil requiert le marqueur exact, un véritable montage, un disque distinct du staging et l’UUID attendu ; une absence USB est détectée **avant** l’arrêt des producteurs.

Le fichier de credentials reste privé sur le HP et une copie de récupération reste dans les Documents du Mac. Aucun secret ne doit être ajouté au dépôt, aux unités ou à fstab. Garder le dossier de configuration en `0700`, ses fichiers en `0600`, propriétaire `debian`.

## Préparation revue et activation séparée

Copier les scripts validés et ce paquet dans les répertoires S236, puis :

```sh
sudo /home/debian/s236-tools/duplicati/install-usb-schedule.sh
findmnt -rn -M /mnt/workplace-backup -o TARGET,FSTYPE,UUID
systemd-analyze verify /etc/systemd/system/workplace-backup.service /etc/systemd/system/workplace-backup.timer
```

L’installateur ajoute uniquement l’entrée exFAT prévue si aucune entrée différente ne couvre déjà cet UUID ou ce point de montage. Il conserve une copie privée de fstab avant modification. Le montage actuel n’est pas démonté ou remonté. `nofail` permet le démarrage sans USB ; l’automount tente un montage à l’accès, avec délai device/mount de 15 secondes. Les montages par UUID et les checks `findmnt` empêchent de sauvegarder sur un répertoire de repli du disque interne.

Pour vérifier le profil et ses permissions sans lancer d’export, exécuter en tant que `debian` :

```sh
cd /home/debian/s236-tools/duplicati
python3 - <<'PY'
import json
from pathlib import Path
import transport
profile=json.loads(Path('/home/debian/.config/workplace-backups/usb-profile.json').read_text())
transport.validate_profile(profile, Path('/home/debian/.local/share/workplace-backups'))
transport.credentials(profile['credentials'])
print('USB et credentials validés')
PY
```

Après le transfert réel vérifié et la répétition de restauration, l’opérateur peut activer la cadence autorisée :

```sh
sudo systemctl start workplace-backup.service
systemctl show workplace-backup.service -p Result -p ExecMainStatus
sudo systemctl enable --now workplace-backup.timer
systemctl list-timers workplace-backup.timer
```

Le premier lancement manuel assure une génération fraîche dès la mise en service ; vérifier son transfert réussi avant de compter sur la cadence. Le timer tourne à 00h00 et 12h00 (heure locale du HP), avec au plus 15 minutes de décalage, et rattrape un passage manqué au redémarrage (`Persistent=true`). Le montage automount est généré par fstab et sera disponible au prochain démarrage ; si le disque est actuellement monté, ne pas le démonter pour l’activer. Ne pas créer une seconde planification dans l’UI Duplicati.

## Ce que mesure le RPO

L’heure d’acquittement du transfert reste `last_transfer_timestamp`. L’âge des données se calcule avec `last_transferred_source_timestamp`, issu de `manifest.started` de la génération effectivement vérifiée après transfert. Pour plusieurs destinations requises, conserver le point source le plus ancien. Transférer une génération vieille de trois jours aujourd’hui conserve un RPO en échec. Un état ancien dépourvu de ce point prouvé publie `0` jusqu’au prochain transfert vérifié ; il ne prend pas l’heure d’acquittement comme preuve de fraîcheur.

Les métriques publiques sont écrites sans secrets dans `/home/debian/workplace/outils/observabilite/textfile/workplace-backup.prom`. L’objectif RPO est 24 h et la cadence 12 h laisse une marge de reprise. Une clé débranchée ne donne jamais lieu à une sauvegarde de repli ; le job enregistre l’échec et les alertes peuvent le signaler.
