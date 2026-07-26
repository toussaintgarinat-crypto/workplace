#!/usr/bin/env bash
# psql into the kamailio DB. Passes args through:
#   ./bin/psql-kamailio.sh                       # interactive
#   ./bin/psql-kamailio.sh -c "SELECT * FROM dispatcher;"
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker compose exec postgres-kamailio psql -U dinum -d kamailio "$@"
