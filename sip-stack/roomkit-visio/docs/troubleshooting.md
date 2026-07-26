# Troubleshooting

## Kamailio: "no certificate file"

TLS certs missing in `./certs/`. Run `make certs` (copies from `$MEET_CERTS`, default `../meet/certs`, else self-signs). Override the source: `MEET_CERTS=path/to/meet/certs make certs`. Force a self-signed pair: `make certs-regen`. Drop the `5061:5061/tcp` mapping in `compose.yml` to disable SIP/TLS.

## livekit-sip: "websocket: bad handshake" or connect refused

livekit-sip can't reach meet's livekit on `localhost:7880`:

```sh
curl -i http://localhost:7880
ss -tlnp | grep 7880
```

Start meet's livekit from your meet checkout: `docker compose up -d livekit redis`.

## "address already in use" on 5060 / 5080

Another container holds the port. Stop matching services from a meet checkout:

```sh
cd path/to/meet
docker compose rm -fs kamailio rtpengine livekit-sip kamailio-cisco \
  prometheus loki promtail grafana rtpengine-exporter kamailio-exporter
```

## One-way audio

```sh
docker compose exec rtpengine rtpengine-ctl ng list
```

Confirm `MY_IP_ADDR` matches the host LAN IP (`make show`), rtpengine advertises it via `--interface`, and the RTP range isn't filtered upstream (`sudo iptables -L -n -v`).

## "no free RTP port"

Widen the range in three places together:

- `docker/rtpengine/rtpengine.conf` → `port-min` / `port-max`
- `docker/livekit-sip/config/livekit-sip.yaml` → `rtp_port`
- `compose.yml` → rtpengine `ports:` block

## Postgres tables missing after first boot

Re-seed:

```sh
make destroy
make start
```

If kamailio raced initdb: `docker compose restart kamailio`.

## OVH trunk not registering

```sh
make sql Q="UPDATE uacreg SET auth_password='YOUR_PASSWORD' WHERE l_uuid='0033972122011';"
docker compose restart kamailio
```

## Grafana dashboards empty

Open http://localhost:9190/targets. For any DOWN target, check the exporter (`docker compose --profile monitoring ps`) and that `prometheus.yml` targets match.
