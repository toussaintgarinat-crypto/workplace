#!/bin/bash
# 02-create-lxc.sh — Crée les 7 LXC sur Proxmox
# Prérequis : 01-create-network.sh exécuté
# Prérequis : template Ubuntu 22.04 téléchargé (voir commande ci-dessous)
#
# Télécharger le template si absent :
#   pveam update && pveam download local ubuntu-22.04-standard_22.04-1_amd64.tar.zst

set -e

STORAGE="local-lvm"   # Change si ton stockage a un autre nom (vérifie avec : pvesm status)
TEMPLATE="local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst"

# CTID  HOSTNAME     RAM(Mo) CPU  DISK(Go) IP_vmbr1
LXC_LIST=(
  "100  infra        1536    2    20       10.10.10.2"
  "101  forge        3072    4    40       10.10.10.10"
  "102  oria         2560    4    30       10.10.10.20"
  "103  mempalace    1536    2    20       10.10.10.30"
  "104  assistant    1024    2    20       10.10.10.40"
  "105  gateway       512    2    10       10.10.10.50"
  "106  ollama-hp    8192    6    60       10.10.10.60"
)

for entry in "${LXC_LIST[@]}"; do
  read -r CTID HOSTNAME MEM CORES DISK IP <<< "$entry"

  echo ""
  echo "═══════════════════════════════════════════"
  echo "  Création LXC $CTID — $HOSTNAME ($IP)"
  echo "═══════════════════════════════════════════"

  pct create "$CTID" "$TEMPLATE" \
    --hostname "$HOSTNAME" \
    --memory "$MEM" \
    --cores "$CORES" \
    --net0 "name=eth0,bridge=vmbr0,ip=dhcp" \
    --net1 "name=eth1,bridge=vmbr1,ip=${IP}/24,gw=10.10.10.1" \
    --storage "$STORAGE" \
    --rootfs "${STORAGE}:${DISK}" \
    --features "nesting=1,keyctl=1" \
    --unprivileged 0 \
    --ostype ubuntu \
    --start 0

  # Autostart au boot Proxmox
  pct set "$CTID" --onboot 1

  pct start "$CTID"
  sleep 3

  echo "==> LXC $CTID ($HOSTNAME) démarré ✓"
done

echo ""
echo "✓ Tous les LXC créés. Prochaine étape : 03-setup-docker.sh"
echo ""
echo "Vérification rapide :"
for entry in "${LXC_LIST[@]}"; do
  read -r CTID HOSTNAME _ _ _ IP <<< "$entry"
  STATUS=$(pct status "$CTID" | awk '{print $2}')
  echo "  LXC $CTID $HOSTNAME : $STATUS — $IP"
done
