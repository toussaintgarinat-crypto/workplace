#!/usr/bin/env bash
# Reload kamailio's address whitelist and dispatcher tables from the DB.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose exec kamailio kamcmd permissions.addressReload
docker compose exec kamailio kamcmd dispatcher.reload
echo "Reloaded address + dispatcher."
