#!/bin/bash
# S237 exercise on an over-committed hypervisor: return the guest page cache to the
# host every minute (virtio-balloon free page reporting) to protect production VMs.
# Usage: host_pressure.sh <private-inventory>
set -euo pipefail
IP=$(sed -n "s/^ *ansible_host: //p" "$1" | head -1); [ -n "$IP" ] || exit 2
ssh -o BatchMode=yes debian@"$IP" 'systemctl is-active -q s237-dropcaches || sudo systemd-run --unit=s237-dropcaches --description="S237 exercise: return page cache to host" /bin/sh -c "while true; do sync; echo 1 > /proc/sys/vm/drop_caches; sleep 60; done" >/dev/null; systemctl is-active s237-dropcaches'
