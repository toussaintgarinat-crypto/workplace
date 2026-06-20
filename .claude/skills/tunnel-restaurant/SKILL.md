---
name: tunnel-restaurant
description: >
  Relance le tunnel HTTPS jetable (cloudflared) qui expose la brique restaurant (port 6010)
  pour que les QR de table soient scannables depuis N'IMPORTE QUEL téléphone (4G/à distance),
  puis écrit l'URL du tunnel dans RESTAURANT_PUBLIC_URL et recrée le conteneur pour que les QR
  l'encodent. Solution temporaire en attendant un hébergement permanent. Use when user says
  "relance le tunnel resto", "tunnel restaurant", "expose le restaurant", "QR scannable",
  "le QR ne marche pas à distance", "nouvelle url restaurant", "tunnel-restaurant".
---

# Relancer le tunnel de la brique restaurant (Workplace)

Contexte : la brique **restaurant** tourne sur `localhost:6010`. Les **QR de table** encodent
l'URL `RESTAURANT_PUBLIC_URL/carte/<code>`. Si cette variable est vide, l'URL est déduite de la
requête = `localhost` → **injoignable depuis un téléphone**. Pour une démo « partout » (4G,
client distant), on expose le 6010 par un **tunnel cloudflared jetable** dont l'URL
`*.trycloudflare.com` **change à chaque redémarrage** → il faut la réécrire dans le `.env`
racine ET **recréer le conteneur** pour que les QR la prennent.

Le client gère déjà `wss://` en HTTPS → carte, commande, paiement et addition live marchent
à travers le tunnel. Exécute les étapes dans l'ordre.

## 1. Vérifier que la brique restaurant répond
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6010/sante
```
- `200` → OK, passe à l'étape 2.
- Sinon → la démarrer puis re-tester :
```bash
docker compose -f /Users/garinat_t/Desktop/Workplace/briques/restaurant/docker-compose.yml up -d
```

## 2. Tuer un éventuel ancien tunnel (évite les orphelins)
```bash
pkill -f "cloudflared tunnel --url http://localhost:6010" 2>/dev/null; echo "anciens tunnels 6010 arrêtés"
```

## 3. Lancer un nouveau tunnel EN ARRIÈRE-PLAN
Lance cette commande avec `run_in_background: true` (elle ne rend jamais la main) :
```bash
cloudflared tunnel --url http://localhost:6010 > /tmp/cf_restaurant.log 2>&1
```

## 4. Récupérer la nouvelle URL (poll du log)
```bash
for i in $(seq 1 30); do url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf_restaurant.log | head -1); [ -n "$url" ] && break; sleep 1; done; echo "URL_TUNNEL=$url"
```
Si vide après 30 s, relire `/tmp/cf_restaurant.log` (vérifier `which cloudflared`).

## 5. Écrire l'URL dans le .env racine + recréer le conteneur
Indispensable : le conteneur lit `RESTAURANT_PUBLIC_URL` à son démarrage → sans recreate, les
QR garderaient l'ancienne URL. (La variable passe par `env_file`, surtout NE PAS la remettre en
`environment:` dans la compose : ce serait écrasé par du vide — piège « env shadow ».)
```bash
cd /Users/garinat_t/Desktop/Workplace
python3 - "$url" <<'PY'
import re,sys
u=sys.argv[1]; p=".env"; s=open(p).read()
if re.search(r'^RESTAURANT_PUBLIC_URL=',s,flags=re.M):
    s=re.sub(r'^RESTAURANT_PUBLIC_URL=.*$',f'RESTAURANT_PUBLIC_URL={u}',s,flags=re.M)
else:
    s+=f'\nRESTAURANT_PUBLIC_URL={u}\n'
open(p,'w').write(s)
print("RESTAURANT_PUBLIC_URL =", u)
PY
docker compose -f briques/restaurant/docker-compose.yml up -d
```

## 6. Vérifier que les QR encodent bien l'URL du tunnel
Le DNS local (routeur) peut filtrer `trycloudflare.com` → curl direct = échec côté Mac. On
vérifie donc l'URL **encodée dans le QR** (en-tête `X-URL-Client`), ce qui suffit :
```bash
cd /Users/garinat_t/Desktop/Workplace
# compte démo (sinon adapter) ; le code de table importe peu, on veut l'URL encodée
EMAIL=$(cut -d'|' -f1 /tmp/demo_vincept.txt 2>/dev/null)
S=$(curl -s -m6 http://localhost:6010/auth/connexion -H 'Content-Type: application/json' -d "{\"email\":\"$EMAIL\",\"mot_de_passe\":\"motdepasse1\"}" | python3 -c "import sys,json;print(json.load(sys.stdin).get('session',''))" 2>/dev/null)
RID=$(cut -d'|' -f3 /tmp/demo_vincept.txt 2>/dev/null)
TID=$(curl -s -m6 "http://localhost:6010/restaurants/$RID/tables" -H "Authorization: Bearer $S" | python3 -c "import sys,json;print(json.load(sys.stdin)['tables'][0]['id'])" 2>/dev/null)
curl -s -m6 -D - -o /dev/null "http://localhost:6010/restaurants/$RID/tables/$TID/qr.svg" -H "Authorization: Bearer $S" | grep -i x-url-client
```
Attendu : `x-url-client: https://<...>.trycloudflare.com/carte/<code>`.
(Optionnel, prouver le tunnel malgré le DNS local : `ip=$(nslookup <host> 1.1.1.1 | awk '/Address/{print $2}' | tail -1); curl -s --resolve "<host>:443:$ip" https://<host>/sante`.)

## 7. Donner l'URL à l'utilisateur + le mode d'emploi
- Affiche l'URL du tunnel.
- **Pour scanner** : rouvrir l'onglet **Tables & QR** dans le back-office (les QR se régénèrent
  avec la nouvelle URL) et scanner avec le téléphone.

## Notes & limites honnêtes
- **DNS** : ce routeur (`192.168.1.254`) renvoie NXDOMAIN sur `*.trycloudflare.com`. Conséquence :
  le **Mac** et un **téléphone sur le même Wi-Fi** ne résoudront pas l'URL du tunnel. Sur **4G**
  (DNS opérateur), ça marche. Donc : tunnel = démo **à distance / en 4G** ; pour une démo
  **sur place même Wi-Fi**, préférer l'**IP LAN** (`RESTAURANT_PUBLIC_URL=http://192.168.1.101:6010`,
  cf. ce même fichier `.env`) — relancer alors un recreate.
- Le tunnel vit **tant que le processus tourne** (dans la session Claude Code) ; il retombe à la
  fermeture/au reboot → **relancer ce skill** (l'URL aura changé → re-recreate). C'est pour ça
  qu'il faut le refaire à chaque lancement de l'app.
- **Permanent** = Cloudflare Tunnel nommé (domaine fixe) ou domaine + reverse-proxy sur le **HP
  Proxmox** (cf. roadmap déploiement) ; ce skill deviendra alors inutile.
- N'expose **que** la brique restaurant (front client gardé par le code de table). Ne pas
  tunneliser le Cœur (5100) en clair.
