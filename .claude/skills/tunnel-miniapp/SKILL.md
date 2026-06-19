---
name: tunnel-miniapp
description: >
  Relance le tunnel HTTPS jetable (cloudflared) qui expose la Mini App Telegram de Workplace
  (brique connexion, port 5870) et donne la NOUVELLE URL à coller dans BotFather. Solution
  temporaire en attendant le déploiement permanent sur Proxmox. Use when user says "relance
  le tunnel", "recrée le tunnel", "nouveau tunnel", "nouvelle url mini app", "remets la mini
  app en ligne", "tunnel telegram", "tunnel-miniapp".
---

# Relancer le tunnel de la Mini App Telegram (Workplace)

Contexte : la Mini App Telegram (l'app Workplace complète, sprint S79) est servie par la
**brique connexion** sur `localhost:5870` (chemin `/miniapp`). Telegram exige une **URL HTTPS
publique** ; en attendant le Proxmox, on l'expose par un **tunnel cloudflared jetable** dont
l'URL `*.trycloudflare.com` **change à chaque redémarrage** → il faut la recoller dans BotFather.

Bot concerné : **@MonAssistantWorkplace_bot**. Exécute les étapes dans l'ordre.

## 1. Vérifier que la brique connexion répond
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5870/miniapp
```
- `200` → OK, passe à l'étape 2.
- Sinon → la démarrer puis re-tester :
```bash
docker compose -f /Users/garinat_t/Desktop/Workplace/briques/connexion/docker-compose.yml up -d
```

## 2. Tuer un éventuel ancien tunnel (évite les orphelins)
```bash
pkill -f "cloudflared tunnel --url http://localhost:5870" 2>/dev/null; echo "anciens tunnels arrêtés"
```

## 3. Lancer un nouveau tunnel EN ARRIÈRE-PLAN
Lance cette commande avec `run_in_background: true` (elle ne rend jamais la main) :
```bash
cloudflared tunnel --url http://localhost:5870 > /tmp/cf_miniapp.log 2>&1
```

## 4. Récupérer la nouvelle URL (poll du log)
```bash
for i in $(seq 1 25); do url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf_miniapp.log | head -1); [ -n "$url" ] && break; sleep 1; done; echo "URL=$url"; [ -n "$url" ] && curl -s -o /dev/null -w "  /miniapp : %{http_code}\n" "$url/miniapp"
```
Attendu : une URL + `/miniapp : 200`. Si vide après 25 s, relire `/tmp/cf_miniapp.log` (le
binaire `cloudflared` doit être installé : `which cloudflared`).

## 5. Donner à l'utilisateur l'URL + les étapes BotFather
Affiche **l'URL complète à coller** : `<url>/miniapp`, puis ce pas-à-pas :
1. Ouvrir **@BotFather**
2. `/mybots` → **@MonAssistantWorkplace_bot**
3. **Bot Settings → Menu Button → Edit menu button URL**
4. Coller `<url>/miniapp`
5. Rouvrir la Mini App dans Telegram

## Notes
- Le tunnel reste valable **tant que le processus tourne** (il vit dans la session Claude
  Code active) ; il retombe si la session se ferme ou la machine redémarre → relancer ce skill.
- Solution **temporaire**. Le permanent = Cloudflare Tunnel nommé (domaine) ou domaine +
  reverse-proxy sur le **HP Proxmox** (cf. roadmap déploiement). À ce moment-là, ce skill
  deviendra inutile.
- Ne PAS exposer le Cœur (5100) directement : seule la brique connexion (front gardé par
  initData → cookie de session) doit être tunnelisée.
