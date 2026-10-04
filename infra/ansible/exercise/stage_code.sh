#!/bin/bash
# S237 exercise: transfer a Git bundle of the release and expose it as a bare repository.
# Usage: stage_code.sh <vm-ip> <bundle> <full-sha>
set -euo pipefail
IP=$1; BUNDLE=$2; SHA=$3
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || exit 2
scp -q "$BUNDLE" debian@"$IP":/home/debian/workplace.bundle
ssh -o BatchMode=yes debian@"$IP" "test -d /home/debian/workplace.git || git clone -q --bare /home/debian/workplace.bundle /home/debian/workplace.git; git -C /home/debian/workplace.git fetch -q /home/debian/workplace.bundle '+refs/heads/*:refs/heads/*'; git -C /home/debian/workplace.git cat-file -e $SHA^{commit} && echo ok"
