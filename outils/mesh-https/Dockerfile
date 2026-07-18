# Caddy + module DNS DuckDNS (nécessaire au challenge ACME DNS-01 de Let's Encrypt).
# L'image officielle caddy:2 ne l'embarque pas → on la reconstruit avec xcaddy.
FROM caddy:2.10-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/duckdns

FROM caddy:2.10
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
