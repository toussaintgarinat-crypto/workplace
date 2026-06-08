#!/bin/bash
# 01-create-network.sh — Crée le bridge interne vmbr1 sur Proxmox
# À exécuter UNE SEULE FOIS sur le host Proxmox (pas dans un LXC)
# Résultat : vmbr1 = 10.10.10.1/24, NAT vers internet via vmbr0

set -e

INTERFACES_FILE="/etc/network/interfaces"

if grep -q "vmbr1" "$INTERFACES_FILE"; then
  echo "vmbr1 déjà présent dans $INTERFACES_FILE — rien à faire."
  exit 0
fi

cat >> "$INTERFACES_FILE" << 'EOF'

auto vmbr1
iface vmbr1 inet static
    address 10.10.10.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    post-up   echo 1 > /proc/sys/net/ipv4/ip_forward
    post-up   iptables -t nat -A POSTROUTING -s '10.10.10.0/24' -o vmbr0 -j MASQUERADE
    post-down iptables -t nat -D POSTROUTING -s '10.10.10.0/24' -o vmbr0 -j MASQUERADE
EOF

echo "==> vmbr1 ajouté à $INTERFACES_FILE"
echo "==> Activation du bridge..."
ifup vmbr1

echo "==> vmbr1 10.10.10.1/24 actif ✓"
echo ""
echo "Plan IP LXC :"
echo "  10.10.10.2   → LXC 100  infra     (Traefik + Keycloak)"
echo "  10.10.10.10  → LXC 101  forge"
echo "  10.10.10.20  → LXC 102  oria"
echo "  10.10.10.30  → LXC 103  mempalace"
echo "  10.10.10.40  → LXC 104  assistant"
echo "  10.10.10.50  → LXC 105  gateway"
echo "  10.10.10.60  → LXC 106  ollama-hp"
