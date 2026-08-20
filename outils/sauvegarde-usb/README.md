# Sauvegarde portable — préparation de la clé + montage automatique sur le HP

Sur le modèle de `outils/sauvegarde/` (MinIO local, pour Litestream/WAL-G — approche
abandonnée pour cet usage, cf. `docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md`),
ce dossier prépare une sauvegarde **portable, à la demande, sans cloud**.

## 1. Préparer la clé (une seule fois)

1. Formater la clé en ext4 (ou une autre FS Linux) avec le label `WORKPLACE-USB` :
   `sudo mkfs.ext4 -L WORKPLACE-USB /dev/sdX1` (remplacer `sdX1` par la bonne partition —
   vérifier avec `lsblk` avant, ne JAMAIS deviner le device).
2. La monter une fois à la main, y créer le fichier sentinelle, la démonter :
   ```
   sudo mount /dev/sdX1 /mnt/sauvegarde-usb
   sudo touch /mnt/sauvegarde-usb/.cle-sauvegarde-workplace
   sudo umount /mnt/sauvegarde-usb
   ```

## 2. Installer le montage automatique sur le HP

```
sudo cp 95-workplace-usb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Rebrancher la clé : elle doit apparaître montée sur `/mnt/sauvegarde-usb` sans action
manuelle (`mount | grep sauvegarde-usb` pour vérifier).

## 3. Utilisation

Une fois la clé branchée (montée automatiquement), demander à l'assistant « sauvegarde sur
la clé » ou utiliser le panneau 💾 Sauvegarde portable (clé USB), sur l'onglet Assistant du
dashboard. Pour restaurer sur une autre machine, voir `docs/INSTALLATION-MACHINE-NEUVE.md`.
