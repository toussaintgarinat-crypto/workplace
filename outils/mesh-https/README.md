# mesh-https — accès distant HTTPS au Cœur via le mesh NetBird

Safari (iOS) force le `https://` ; le Cœur ne parle que HTTP sur `:5100`. Ce petit **Caddy**
(déployé sur la VM `192.168.1.89`) termine le TLS sur l'**IP mesh** et proxifie le Cœur —
sans exposer le moindre port sur la box (tout reste dans le mesh chiffré).

```
📱 iPhone (mesh) ──https──▶ Caddy :443 (IP mesh 100.124.248.226) ──http──▶ Cœur localhost:5100
```

## Variante 1 — CA interne (déployée, souveraine, sans domaine)
```bash
# sur la VM
docker compose up -d
```
Accès : `https://100.124.248.226/dashboard`. Safari affiche un avertissement (CA non
connue) → **Afficher les détails → visiter ce site web**. Contournable en 1 tap ; pour
zéro avertissement, installer la CA de Caddy sur l'iPhone (fichier
`/data/caddy/pki/authorities/local/root.crt` dans le volume `caddy_data`), ou passer à la
variante 2.

## Variante 2 — vrai certificat DuckDNS (zéro avertissement, gratuit)
Fonctionne derrière le NAT (challenge **DNS-01**, aucun port entrant).
1. Crée un sous-domaine gratuit sur https://duckdns.org (ex. `monworkplace.duckdns.org`) et
   récupère ton **token**.
2. Pointe le sous-domaine sur l'**IP mesh** :
   ```bash
   curl "https://www.duckdns.org/update?domains=monworkplace&token=<TOKEN>&ip=100.124.248.226"
   ```
3. Adapte `Caddyfile.duckdns` (nom de domaine + email), puis sur la VM :
   ```bash
   cp Caddyfile.duckdns Caddyfile
   echo "DUCKDNS_TOKEN=<TOKEN>" > .env
   docker compose -f docker-compose.duckdns.yml up -d --build
   ```
Accès : `https://monworkplace.duckdns.org/dashboard` (résout vers l'IP mesh pour les pairs).

## Fichiers
- `Caddyfile` / `docker-compose.yml` — variante 1 (active).
- `Caddyfile.duckdns` / `Dockerfile.duckdns` / `docker-compose.duckdns.yml` — variante 2.

## Limites honnêtes
Le dashboard + le chat passent. Certaines **iframes de briques** et le **WebSocket voix**
pointent vers des URLs internes (localhost/host.docker.internal) non résolues depuis le
téléphone → expérience partielle à distance (chantier séparé). Cf. `GUIDE-mesh-netbird.md`.
