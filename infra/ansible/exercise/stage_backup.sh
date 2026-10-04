#!/bin/bash
# S237 exercise: copy the encrypted Duplicati destination, read-only, from the USB
# medium attached to production into the exercise VM. Ciphertext only; no export.
# Usage: stage_backup.sh <vm-ip> <profile-id> <medium-identity>
set -euo pipefail
IP=$1; PROFILE=$2; IDENTITY=$3; SOURCE=${SOURCE:-debian@192.168.1.89}; MEDIUM=/mnt/workplace-backup
[[ $PROFILE =~ ^[a-z0-9-]+$ ]] || exit 2
ssh -o BatchMode=yes debian@"$IP" 'sudo install -d -m 0700 /srv/workplace-rehearsal/backups/remote'
ssh -o BatchMode=yes "$SOURCE" "test \"\$(cat $MEDIUM/.workplace-s236-target)\" = '$IDENTITY' && tar -C $MEDIUM/workplace -cf - $PROFILE" \
  | ssh -o BatchMode=yes debian@"$IP" "sudo tar -C /srv/workplace-rehearsal/backups/remote -xf - && sudo du -sb /srv/workplace-rehearsal/backups/remote/$PROFILE"
