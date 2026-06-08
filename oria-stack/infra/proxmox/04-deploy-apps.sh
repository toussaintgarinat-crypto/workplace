#!/bin/bash
# 04-deploy-apps.sh — Copie chaque app dans son LXC et lance le déploiement
# À exécuter depuis le Mac (SSH vers Proxmox, puis pct push)
# Prérequis : SSH configuré vers le HP, apps buildées localement
#
# Usage : PROXMOX_HOST=192.168.1.X bash 04-deploy-apps.sh

set -e

PROXMOX_HOST="${PROXMOX_HOST:?Définis PROXMOX_HOST=IP_DU_HP}"
WORKSPACE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# Crée une archive tar de chaque app et la pousse dans le LXC correspondant
push_app() {
  local CTID="$1"
  local APP="$2"
  local COMPOSE_FILE="${3:-docker-compose.yml}"

  echo ""
  echo "─── Push $APP → LXC $CTID ───────────────────"

  # Copie via SSH + pct push (tar pour préserver les symlinks)
  tar -czf "/tmp/${APP}.tar.gz" -C "$WORKSPACE_DIR" \
    --exclude="$APP/node_modules" \
    --exclude="$APP/.git" \
    --exclude="$APP/dist" \
    "$APP"

  ssh "root@$PROXMOX_HOST" "mkdir -p /opt/workspace/$APP"
  scp "/tmp/${APP}.tar.gz" "root@$PROXMOX_HOST:/tmp/"
  ssh "root@$PROXMOX_HOST" "
    tar -xzf /tmp/${APP}.tar.gz -C /opt/workspace/
    pct push $CTID /opt/workspace/$APP /opt/$APP --perms 0755
  "
  rm "/tmp/${APP}.tar.gz"
  echo "==> $APP copié dans LXC $CTID ✓"
}

# Copie via pct push depuis Proxmox host (si déjà sur le HP)
push_app_local() {
  local CTID="$1"
  local APP="$2"

  echo ""
  echo "─── Push local $APP → LXC $CTID ────────────"
  pct push "$CTID" "/opt/workspace/$APP" "/opt/$APP" --perms 0755
  echo "==> $APP copié ✓"
}

echo "==> Ce script doit être adapté selon ta méthode de transfer."
echo ""
echo "Méthode recommandée depuis le Mac :"
echo ""
echo "  # 1. Cloner le repo sur le HP via NetBird"
echo "  ssh root@NETBIRD_HP_IP"
echo "  apt install git"
echo "  git clone https://github.com/toussaintgarinat-crypto/workspace /opt/workspace"
echo ""
echo "  # 2. Dans chaque LXC, monter le dossier du host en bind mount"
echo "  # (ajouter dans /etc/pve/lxc/10X.conf :)"
echo "  #   mp0: /opt/workspace/forge,mp=/opt/forge"
echo "  #   mp1: /opt/workspace/gateway,mp=/opt/gateway"
echo "  # etc."
echo ""
echo "  # 3. Ou copier avec pct push (un fichier à la fois)"
echo "  pct push 101 /opt/workspace/forge /opt/forge --perms 0755"
echo ""
echo "La méthode bind mount est la plus simple pour des mises à jour fréquentes."
