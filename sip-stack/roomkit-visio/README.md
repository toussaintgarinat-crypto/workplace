# roomkit-visio

Gateway that bridges SIP devices (Cisco, Poly, Aver and other compatible SIP endpoints) and PSTN trunks (OVH) into [LiveKit](https://livekit.io) WebRTC rooms. Handles audio, video, and RTCP end-to-end.

![Roomkit architecture](docs/images/architecture.png)

## Components

- **Kamailio** — SIP proxy / dispatcher. Routes SIP traffic, drives SDP rewrites via rtpengine, handles UAC registration (OVH trunk), reads subscriber / dispatcher / rtpengine state from PostgreSQL.
- **rtpengine** — RTP/RTCP relay between SIP endpoints and livekit-sip. SDES (AES-128) for SRTP/SRTCP, directional routing, `ng` protocol to Kamailio.
- **livekit-sip** — SIP ↔ LiveKit translation (port 5080). SDP negotiation + BFCP, audio transcode (G.711/G.722 ↔ Opus), GStreamer video transcode (H.264 ↔ VP8/VP9), RTCP feedback bridging (PLI/FIR/NACK), up-to-6-tile compositing. Image `livekit-sip:local` (built locally — see [docs/livekit-sip-dev.md](docs/livekit-sip-dev.md)).
- **postgres-kamailio** — Kamailio runtime DB (version, subscriber, dispatcher, address, rtpengine, uacreg).
- **monitoring** (optional) — Prometheus (7-day retention), Grafana (SIP + media dashboards, livekit-sip logs, alerting), Loki, Promtail, exporters.

Details: [docs/architecture.md](docs/architecture.md).

## Prerequisites

- Linux host with Docker.
- A meet compose project on the same host (provides `livekit:7880` and `redis:16379` on localhost).
- Free host ports: `5060/udp+tcp`, `5061/tcp`, `5080/udp+tcp`, `2049/tcp`, `9101/tcp`, `22222/udp`, `20301-20400/udp`, `30001-30100/udp`, `25432/tcp`. With `make start-all`: also `3001/tcp`, `9190/tcp`, `3100/tcp`.

## Recommended layout

```
parent/
├── meet/             # https://github.com/suitenumerique/meet
├── roomkit-visio/    # this repo
└── livekit-sip/      # https://github.com/suitenumerique/livekit-sip @ branch sip-video-v2
```

```sh
git clone -b sip-video https://github.com/suitenumerique/livekit-sip.git ../livekit-sip
```

Defaults: `MEET_CERTS=../meet/certs`, `LIVEKIT_SIP_SRC=../livekit-sip`. Override per-command or in `.env`.

## Quickstart

```sh
# 1. Start meet (livekit + redis) from the meet checkout
cd ../meet
docker compose up -d livekit livekit-egress redis postgresql app-dev

# 2. Bootstrap + start
cd ../roomkit-visio
make bootstrap
make start          # add `-all` for the monitoring stack
```

Verify:

```sh
make sql Q="SELECT destination FROM dispatcher;"
make ports
make logs SVC=livekit-sip
```

Register a SIP device on the LAN to `${MY_IP_ADDR}:5060` and dial `555`.

## Make targets

| Target | Action |
| --- | --- |
| `make bootstrap` | `.env` + TLS certs + `livekit-sip:local` build + pre-pull other images. |
| `make start` / `make start-all` | Up the SIP stack (and monitoring with `-all`). |
| `make stop` | Stop containers. |
| `make down` | Stop + remove containers (keep volumes). |
| `make destroy` | Stop + remove containers + drop volumes. Prompts. |
| `make restart` | Restart all containers. |
| `make logs` / `make logs SVC=kamailio` | Follow logs. |
| `make status` | `docker compose ps`. |
| `make ports` | Host ports owned by roomkit-visio. |
| `make psql` / `make sql Q="..."` | psql shell / one-shot query. |
| `make reload` | `kamcmd permissions.addressReload + dispatcher.reload`. |
| `make dispatcher` / `make rtpengine-show` | Inspect kamailio state. |
| `make show` | Print LAN IP, cert and `.env` presence. |
| `make clean` | `make down` + delete `.env` and `certs/tls.*`. |
| `make gst-clear` | Wipe `./gst-dots/*.dot` ([docs/livekit-sip-dev.md](docs/livekit-sip-dev.md#gstreamer-pipeline-dumps)). |
| `make sip-build` / `make sip-rebuild` | Build `livekit-sip:local` (and force-recreate the container). |

## livekit-sip

```sh
make sip-build       # docker build livekit-sip:local from $LIVEKIT_SIP_SRC (default ../livekit-sip)
make sip-rebuild     # build + force-recreate the running container
```

`make bootstrap` runs `sip-build`. Details + GStreamer debugging: [docs/livekit-sip-dev.md](docs/livekit-sip-dev.md).

## Layout

```
.
├── Makefile
├── compose.yml
├── .env.example
├── bin/
│   ├── psql-kamailio.sh
│   └── reload-kamailio.sh
├── certs/                      # gitignored; populated by `make certs`
├── gst-dots/                   # gitignored; livekit-sip GStreamer .dot dumps
├── docker/
│   ├── kamailio/
│   ├── livekit-sip/config/
│   ├── rtpengine/
│   ├── postgres/initdb/
│   ├── prometheus/
│   ├── promtail/
│   └── grafana/provisioning/
└── docs/
    └── images/
```

## Docs

- [docs/architecture.md](docs/architecture.md)
- [docs/networking.md](docs/networking.md)
- [docs/postgres.md](docs/postgres.md)
- [docs/kamailio.md](docs/kamailio.md)
- [docs/monitoring.md](docs/monitoring.md)
- [docs/livekit-sip-dev.md](docs/livekit-sip-dev.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
