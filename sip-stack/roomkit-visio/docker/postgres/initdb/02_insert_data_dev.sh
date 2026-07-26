#!/usr/bin/env bash
# Seeds the kamailio DB. Runs once via postgres /docker-entrypoint-initdb.d.
set -euo pipefail

: "${MY_IP_ADDR:?MY_IP_ADDR must be set on the postgres-kamailio service in compose.yml}"

# /24 the host belongs to.
LAN_NETWORK="${MY_IP_ADDR%.*}.0"

echo "Seeding kamailio dev data: MY_IP_ADDR=${MY_IP_ADDR}, LAN=${LAN_NETWORK}/24"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" <<SQL
-- Table versions.
INSERT INTO version (table_name, table_version) VALUES ('subscriber', 7) ON CONFLICT (table_name) DO UPDATE SET table_version = 7;
INSERT INTO version (table_name, table_version) VALUES ('dispatcher', 4) ON CONFLICT (table_name) DO UPDATE SET table_version = 4;
INSERT INTO version (table_name, table_version) VALUES ('rtpengine',  1) ON CONFLICT (table_name) DO UPDATE SET table_version = 1;
INSERT INTO version (table_name, table_version) VALUES ('address',    6) ON CONFLICT (table_name) DO UPDATE SET table_version = 6;
INSERT INTO version (table_name, table_version) VALUES ('trusted',    6) ON CONFLICT (table_name) DO UPDATE SET table_version = 6;
INSERT INTO version (table_name, table_version) VALUES ('uacreg',     5) ON CONFLICT (table_name) DO UPDATE SET table_version = 5;

-- Dispatcher destination → livekit-sip on the host.
INSERT INTO dispatcher (setid, destination, flags, priority, attrs, description)
    SELECT 1, 'sip:${MY_IP_ADDR}:5080;transport=tcp', 0, 0, '', 'DEV LiveKit-SIP'
    WHERE NOT EXISTS (SELECT 1 FROM dispatcher WHERE setid = 1 AND destination = 'sip:${MY_IP_ADDR}:5080;transport=tcp');

-- RTPEngine ng socket + advertised external IP.
INSERT INTO rtpengine (setid, url, weight, disabled, external_ip)
    SELECT 1, 'udp:${MY_IP_ADDR}:22222', 1, 0, '${MY_IP_ADDR}'
    WHERE NOT EXISTS (SELECT 1 FROM rtpengine WHERE setid = 1 AND url = 'udp:${MY_IP_ADDR}:22222');

-- IP whitelist (/24 derived from MY_IP_ADDR).
INSERT INTO address (grp, ip_addr, mask, port, tag)
    SELECT 1, '${LAN_NETWORK}', 24, 0, 'DEV local network'
    WHERE NOT EXISTS (SELECT 1 FROM address WHERE grp = 1 AND ip_addr = '${LAN_NETWORK}');

-- OVH SIP trunk row, disabled (empty auth_password).
INSERT INTO uacreg (l_uuid, l_username, l_domain, r_username, r_domain,
    realm, auth_username, auth_password, auth_ha1, auth_proxy,
    expires, flags, reg_delay, contact_addr, socket)
SELECT '0033555555555', '0033555555555', 'siptrunk.ovh.net',
    '0033555555555', 'siptrunk.ovh.net', 'siptrunk.ovh.net',
    '0033555555555', '', '', 'sip:siptrunk.ovh.net',
    3600, 0, 0, '', ''
WHERE NOT EXISTS (SELECT 1 FROM uacreg WHERE l_uuid = 'P');
SQL

echo "Seed complete."
