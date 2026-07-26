# Kamailio

`docker/kamailio/kamailio.cfg` is the active config.

## Env vars (set in compose.yml)

| Env | Effect |
| --- | --- |
| `MY_IP_ADDR` | IP placed in SIP `Via` / `Contact`. Read from `.env`. |
| `SIP_REALM`, `SIP_ADVERTISE_IP` | Set to `MY_IP_ADDR` in dev. |
| `KAMAILIO_DB_URL` | `postgres://dinum:pass@localhost:25432/kamailio`. |
| `ENABLE_IP_WHITELIST` | `true` enforces the `address` whitelist via the permissions module. |
| `CTL_BINRPC` | BINRPC port (`2049`). |

Dispatcher and rtpengine endpoints live in postgres tables. Edit via `make sql Q="..."` then `make reload`.

## Hot reload

```sh
make reload
# = kamcmd permissions.addressReload + kamcmd dispatcher.reload
```

`uac.reg_reload` is BINRPC-only — for an OVH password change, run `docker compose restart kamailio`.

## Logs / debug

```sh
docker compose logs -f kamailio
docker compose exec kamailio kamcmd core.uptime
docker compose exec kamailio kamcmd dispatcher.list
docker compose exec kamailio kamcmd rtpengine.show all
docker compose exec kamailio kamcmd permissions.addressDump
```

## TLS

Kamailio mounts `./certs/tls.crt` and `./certs/tls.key`. `make certs` populates them — copies from `$MEET_CERTS` (default `../meet/certs`) if present, else self-signs with `CN=$(LAN_IP)`. Force a fresh self-signed pair with `make certs-regen`. Drop the `5061:5061/tcp` mapping in `compose.yml` to disable SIP/TLS.
