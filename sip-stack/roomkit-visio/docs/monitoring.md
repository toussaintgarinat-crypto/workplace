# Monitoring

prometheus, grafana, loki, promtail, exporters — gated by the `monitoring` compose profile.

```sh
make start-all      # docker compose --profile monitoring up -d
make stop           # stop everything
make down           # stop + remove containers
```

## Access

| URL | Component | Credentials |
| --- | --- | --- |
| http://localhost:3001 | Grafana | admin / admin (anonymous Viewer enabled) |
| http://localhost:9190 | Prometheus | — |
| http://localhost:3100 | Loki | — |

## Datasources & dashboards

Provisioned from `docker/grafana/provisioning/`:

- Datasources: `prometheus` at `http://localhost:9190` (default), `loki` at `http://localhost:3100`.
- Dashboards: `kamailio.json`, `rtpengine.json`, `livekit-sip.json`.

## Prometheus targets

Defined in `docker/prometheus/prometheus.yml`:

```
- job: livekit-sip   target: localhost:9101
- job: rtpengine     target: localhost:9102
- job: kamailio      target: localhost:9103
```

- `livekit-sip` exposes metrics directly on `:9101` (`prometheus_port` in `livekit-sip.yaml`).
- `rtpengine-exporter` runs `docker/rtpengine/rtpengine_exporter.py`, polls rtpengine NG on `${MY_IP_ADDR}:22222`, exposes `:9102`.
- `kamailio-exporter` scrapes kamailio BINRPC on `${MY_IP_ADDR}:2049`, exposes `:9103`.

## Logs

Promtail tails container stdout/stderr from `/var/run/docker.sock` and ships to Loki at `http://localhost:3100`. Query by container name: `{container="kamailio"}`.
