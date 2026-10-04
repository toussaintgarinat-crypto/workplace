#!/bin/sh
# Prépare fstab + unités. Ne démarre/active aucun service ou timer.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Exécuter cet installateur avec les droits root après revue.' >&2; exit 1; }
bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f /home/debian/s236-tools/duplicati/job.py ]
[ -f /home/debian/s236-tools/coherent/backup.py ]
[ -f /home/debian/s236-tools/coherent/monitor.py ]
[ -f /home/debian/.config/workplace-backups/usb-job.json ]
[ -f /home/debian/.config/workplace-backups/usb-profile.json ]
[ -f "$bundle_dir/workplace-backup-usb.fstab" ]
systemd-analyze verify "$bundle_dir/workplace-backup.service" "$bundle_dir/workplace-backup.timer"
python3 - "$bundle_dir/workplace-backup-usb.fstab" <<'PY'
import json, os, stat, sys, tempfile, time
from pathlib import Path
config=Path('/home/debian/.config/workplace-backups/usb-job.json')
profile=Path('/home/debian/.config/workplace-backups/usb-profile.json')
for p in (config,profile):
 if p.is_symlink() or stat.S_IMODE(p.stat().st_mode)!=0o600 or p.stat().st_uid!=1000:raise SystemExit('Configuration privée requise, propriétaire debian et mode0600')
job=json.loads(config.read_text());target=json.loads(profile.read_text())
if job.get('inventory')!='/home/debian/s236-tools/coherent/inventory-hp.json' or job.get('profiles')!=[str(profile)]:raise SystemExit('Configuration USB différente du profil revu')
if target.get('kind')!='file' or target.get('mount_path')!='/mnt/workplace-backup' or target.get('expected_uuid')!='6A01-B378' or target.get('required') is not True:raise SystemExit('Identité USB requise différente du profil revu')
fstab=Path('/etc/fstab')
if fstab.is_symlink() or not fstab.is_file():raise SystemExit('fstab doit être un fichier normal')
entry=next(line for line in Path(sys.argv[1]).read_text().splitlines() if line and not line.startswith('#'))
existing=fstab.read_text();conflicts=[];present=False
for line in existing.splitlines():
 fields=line.strip().split()
 if not fields or fields[0].startswith('#'):continue
 if fields[0]=='UUID=6A01-B378' or (len(fields)>1 and fields[1]=='/mnt/workplace-backup'):
  if ' '.join(fields)!=entry:conflicts.append(line)
  else:present=True
if conflicts:raise SystemExit('Entrée fstab USB existante différente: revue manuelle requise, aucun changement effectué')
if not present:
 backup=fstab.with_name('fstab.s236-before-'+str(time.time_ns()))
 fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as stream:stream.write(existing)
 fd,temp=tempfile.mkstemp(prefix='.fstab-s236-',dir='/etc')
 try:
  with os.fdopen(fd,'w') as stream:
   stream.write(existing.rstrip('\n')+'\n# S236 USB chiffré, automount facultatif\n'+entry+'\n');stream.flush();os.fsync(stream.fileno())
  os.chmod(temp,stat.S_IMODE(fstab.stat().st_mode));os.replace(temp,fstab)
 finally:Path(temp).unlink(missing_ok=True)
mountpoint=Path('/mnt/workplace-backup')
if mountpoint.is_symlink():raise SystemExit('Point de montage symbolique interdit')
mountpoint.mkdir(mode=0o750,exist_ok=True)
print('fstab USB préparé; volume existant conservé, aucun formatage ni activation.')
PY
install -o root -g root -m 0644 "$bundle_dir/workplace-backup.service" /etc/systemd/system/workplace-backup.service
install -o root -g root -m 0644 "$bundle_dir/workplace-backup.timer" /etc/systemd/system/workplace-backup.timer
systemctl daemon-reload
printf '%s\n' 'Unités préparées. Le timer reste inactif; activer uniquement après les contrôles du runbook.'
