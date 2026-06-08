#!/bin/bash
# 03-setup-docker.sh — Installe Docker dans tous les LXC
# À exécuter sur le host Proxmox (utilise pct exec)
#
# Usage : bash 03-setup-docker.sh
# Usage ciblé : bash 03-setup-docker.sh 101   (un seul LXC)

set -e

CTIDS=("100" "101" "102" "103" "104" "105" "106")

if [[ -n "$1" ]]; then
  CTIDS=("$1")
fi

install_docker() {
  local CTID="$1"
  echo ""
  echo "─── Docker dans LXC $CTID ───────────────────"

  pct exec "$CTID" -- bash -c "
    set -e
    export DEBIAN_FRONTEND=noninteractive

    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \"\$VERSION_CODENAME\") stable\" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

    systemctl enable docker --quiet
    systemctl start docker

    docker --version
    docker compose version
    echo 'Docker OK ✓'
  "
}

for CTID in "${CTIDS[@]}"; do
  install_docker "$CTID"
done

echo ""
echo "✓ Docker installé dans tous les LXC."
echo ""
echo "Prochaine étape :"
echo "  1. Copier les apps dans chaque LXC (voir 04-deploy-apps.sh)"
echo "  2. Renseigner les fichiers .env avec les IPs NetBird"
echo "  3. lancer make start dans chaque LXC"
