#!/bin/sh
set -e
envsubst < /etc/netbird/management.json.template > /tmp/management.json
exec /management --config /tmp/management.json "$@"
