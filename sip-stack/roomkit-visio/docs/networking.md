# Networking

## Host network mode

`kamailio`, `rtpengine`, `livekit-sip`, and the monitoring stack run with `network_mode: host`. They bind on the host's interfaces and reach each other (and meet's services) as `localhost:<port>`.

`postgres-kamailio` runs on the default bridge; 5432 published as `25432`.

## Host port map

| Port | Proto | Service |
| --- | --- | --- |
| 5060 | udp + tcp | kamailio SIP |
| 5061 | tcp | kamailio SIP/TLS |
| 2049 | tcp | kamailio BINRPC |
| 5080 | udp + tcp | livekit-sip SIP |
| 9101 | tcp | livekit-sip prometheus |
| 22222 | udp | rtpengine NG |
| 20301-20400 | udp | rtpengine RTP |
| 30001-30100 | udp | livekit-sip RTP |
| 25432 | tcp | postgres-kamailio |
| 9102 | tcp | rtpengine-exporter (monitoring) |
| 9103 | tcp | kamailio-exporter (monitoring) |
| 9190 | tcp | prometheus (monitoring) |
| 3001 | tcp | grafana (monitoring) |
| 3100 | tcp | loki (monitoring) |

## SDP advertisement

The host IP appears in SIP/SDP in three places, all driven by `MY_IP_ADDR` (from `.env`):

- `MY_IP_ADDR` env on kamailio → SIP Via and Contact headers.
- `--interface=${MY_IP_ADDR}` on rtpengine's command line → SDP `c=` and `m=` for the device leg.
- `external_ip` column in the postgres `rtpengine` table → seeded from `${MY_IP_ADDR}` on first boot.

After changing `MY_IP_ADDR`, run `make destroy && make start` to re-seed postgres.

## Cross-project: meet ↔ roomkit-visio

livekit-sip reaches meet's services at `ws://localhost:7880` and `localhost:16379`.

## Port collisions

```sh
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E '5060|5080|22222|2049'
```

Stop matching services from inside a meet checkout:

```sh
docker compose rm -fs kamailio rtpengine livekit-sip prometheus grafana loki promtail rtpengine-exporter kamailio-exporter
```
