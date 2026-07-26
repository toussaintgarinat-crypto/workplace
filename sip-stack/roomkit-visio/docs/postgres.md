# Postgres (kamailio DB)

A `postgres:16` container holds the kamailio runtime tables. DB `kamailio`, user `dinum` / `pass`, host port `25432`.

## Initial schema + seed data

`docker/postgres/initdb/` is mounted at `/docker-entrypoint-initdb.d`. On a fresh data volume postgres runs the files in alphabetical order:

1. `01_create_schema.sql` — creates tables: `version`, `subscriber`, `dispatcher`, `rtpengine`, `address`, `trusted`, `uacreg`.
2. `02_insert_data_dev.sh` — seeds dev data with `${MY_IP_ADDR}` substituted:
   - `dispatcher` row → `sip:${MY_IP_ADDR}:5080;transport=tcp`.
   - `rtpengine` row → `udp:${MY_IP_ADDR}:22222`, `external_ip = ${MY_IP_ADDR}`.
   - `address` whitelist → `/24` derived from `${MY_IP_ADDR}`.
   - `uacreg` OVH SIP trunk row, disabled (empty `auth_password`).

Initdb runs only on an empty data volume. Re-seed:

```sh
make destroy        # drops the postgres-kamailio volume (confirmation prompt)
make start
```

## Inspect / change at runtime

```sh
make psql
make sql Q="SELECT * FROM dispatcher;"
make sql Q="SELECT * FROM uacreg;"
make dispatcher
```

Hot-reload kamailio after editing `dispatcher` or `address`:

```sh
make reload
```

## Enabling the OVH SIP trunk

```sh
make sql Q="UPDATE uacreg SET auth_password='YOUR_PASSWORD' WHERE l_uuid='0033972122011';"
docker compose restart kamailio
```

## kamailio races initdb on cold start

`service_healthy` covers `pg_isready` but not the initdb scripts. If kamailio errors with missing tables, restart it once the postgres log shows `database system is ready to accept connections`:

```sh
docker compose logs -f postgres-kamailio
docker compose restart kamailio
```
