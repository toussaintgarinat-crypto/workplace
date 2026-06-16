# GUIDE — Mesh NetBird : relier le téléphone, le Cœur et le Muscle (S59)

Ce guide met en place le **« système nerveux »** du partage de puissance de calcul : un
réseau privé chiffré (mesh WireGuard via **NetBird**) qui relie trois machines **sans
ouvrir le moindre port** sur la box internet domestique.

```
   📱 Téléphone (4G/5G)            🧠 Cœur (Proxmox, H24)          💪 Muscle (Mac Apple Silicon)
   navigateur / PWA                core + briques + Gateway        Ollama / LM Studio / llama.cpp
        │                                  │                                 │
        └────────────── mesh NetBird (WireGuard, 100.100.0.0/16) ───────────┘
                                   ▲ aiguillé par le VPS
                        (signal :10000, management :33073, TURN :3478/udp)
```

Le VPS ne voit jamais le contenu (chiffré de bout en bout entre pairs) : il sert
uniquement de **rendez-vous** pour percer les NAT. Si deux pairs peuvent se joindre en
direct, le trafic ne passe même pas par le VPS (P2P) ; sinon il est relayé par le TURN.

> **Honnêteté** : ce guide est *exécutable* mais la preuve LIVE finale (téléphone en 4G →
> réponse calculée par le Mac) se fait sur **ton** VPS + **ton** Mac. Le dépôt fournit
> tout le câblage côté Workplace (entrées Gateway, brique calcul, env) ; le mesh lui-même
> est de l'ops à dérouler une fois.

---

## 0. Pré-requis
- Un **VPS** public (l'« aiguilleur ») avec Docker. Le reverse-proxy Traefik existant
  (`oria-stack/infra/traefik/`) **réserve déjà** les ports NetBird : `10000` (signal),
  `33073` (management), `3478/udp` (TURN). Vérifie qu'ils sont bien forwardés depuis la box.
- Un **nom de domaine** pointant sur le VPS (ex. `mesh.mondomaine.fr`) — NetBird s'auto-TLS.
- Le **Cœur** (Proxmox) et le **Mac** allumables et sous Docker/CLI.

---

## 1. Déployer le plan de contrôle NetBird sur le VPS
NetBird fournit un installeur auto-hébergé qui monte management + signal + relay (TURN) +
dashboard + IdP (Zitadel) correctement configurés entre eux — on s'appuie dessus plutôt
que de réécrire un compose fragile :

```bash
# Sur le VPS
export NETBIRD_DOMAIN=mesh.mondomaine.fr
curl -fsSL https://github.com/netbirdio/netbird/releases/latest/download/getting-started-with-zitadel.sh | bash
```

À la fin, le script affiche l'URL du **dashboard** (`https://mesh.mondomaine.fr`) et les
identifiants admin. Connecte-toi : tu y créeras les clés d'enrôlement (« setup keys »).

> Si tu fais tourner Traefik en frontal : les entrées `netbird-signal` / `netbird-management` /
> `turn-udp` du `traefik.yml` sont là pour router ces flux ; sinon laisse NetBird exposer
> directement ses ports (déjà forwardés).

Crée **une setup key réutilisable** dans le dashboard (Settings → Setup Keys).

---

## 2. Enrôler les trois pairs
Sur **chaque** machine, installer le client puis se rattacher avec la setup key :

```bash
# Cœur (Proxmox) et Muscle (Mac) — client CLI
curl -fsSL https://pkgs.netbird.io/install.sh | sh
netbird up --management-url https://mesh.mondomaine.fr --setup-key <SETUP_KEY>
netbird status        # doit afficher « Connected » + une IP 100.100.x.x
```

- **Mac (Muscle)** : on peut aussi installer l'app de menu NetBird (DMG) et coller la
  même URL + setup key.
- **Téléphone** : installe l'app **NetBird** (iOS/Android), renseigne l'URL de management
  et la setup key. En 4G/5G il rejoint le mesh comme les autres.

Note les **IP mesh** attribuées (ex. Cœur `100.100.0.10`, Mac `100.100.0.1`). Idéalement,
fixe-les / nomme-les dans le dashboard pour qu'elles soient stables.

---

## 3. Servir le LLM sur le Mac (le Muscle)
Au choix (tous OpenAI-compatibles, donc agnostiques côté Workplace) :

```bash
# Ollama (le plus simple) — écoute sur toutes les interfaces pour être joignable via le mesh
OLLAMA_HOST=0.0.0.0:11434 ollama serve
ollama pull llama3.3
# ou LM Studio (serveur :1234/v1) / llama.cpp (--host 0.0.0.0 --port 8080) / mlx_lm.server
```

Vérifie depuis le Cœur, **via l'IP mesh du Mac** :

```bash
curl http://100.100.0.1:11434/api/tags        # Ollama → 200 + liste des modèles
```

---

## 4. Câbler Workplace (côté Cœur)
Dans le `.env` racine (cf. section « Muscle déporté » de `.env.example`) :

```ini
MUSCLE_ACTIF=1
# Parc lu par la brique calcul (une entrée par machine) :
CALCUL_NOEUDS=[{"id":"mac-studio","nom":"Mac Studio","endpoint":"http://100.100.0.1:11434","mac_wol":"AA:BB:CC:DD:EE:01","methode_reveil":["wol","wakeping"],"priorite":10,"modele_gateway":"ollama/llama3.3"}]
# Adresse mesh vue par la Gateway (doit matcher l'endpoint ci-dessus) :
OLLAMA_URL=http://100.100.0.1:11434
# Pour un 2ᵉ muscle non-Ollama : MUSCLE_2_URL=http://100.100.0.2:1234/v1  + modele_gateway "local/muscle-2"
```

Puis **recréer** la Gateway (l'env est figé à la création du conteneur) et (re)lancer la
brique calcul :

```bash
cd briques/gateway && docker compose up -d --force-recreate gateway
cd ../calcul        && docker compose up -d --force-recreate
```

Dans le dashboard du Cœur → **⚙ Cerveau** : coche **« Muscle déporté »**. La tuile d'état
doit afficher le Mac 🟢 (éveillé) ou 🌙 (endormi, réveillable). Premier message → la
réponse est calculée par le Mac (vérifie `modele_utilise` dans le journal d'usage).

---

## 5. Preuve LIVE (le test qui valide S59)
1. Coupe le WiFi du téléphone → **4G/5G uniquement**.
2. Ouvre le dashboard du Cœur via son **IP mesh** (`http://100.100.0.10:5100/dashboard`)
   ou le nom NetBird.
3. Envoie un message. Si le Mac dort, il est réveillé en fond (le 1ᵉʳ message part en mode
   dégradé sur les gratuits, les suivants tombent sur le Mac chaud).
4. **Vérifie qu'aucun port n'est ouvert sur la box** : depuis un réseau externe, un scan
   de l'IP publique de la box ne doit montrer NI 5100, NI 11434, NI 4001 — tout passe par
   le tunnel chiffré. Seuls les ports du **VPS** (80/443/10000/33073/3478) sont publics.

---

## 6. Durcissement
- **Ne mappe pas** les ports du Cœur / de la Gateway / de la brique calcul vers l'extérieur
  de la box : ils ne doivent être joignables **que par le mesh** (et `host.docker.internal`
  en local). Sur le Mac, `ollama serve` n'écoute que pour le mesh (pas de redirection box).
- **CORS** : si tu exposes un front hors iframe, resserre `CORS_ORIGINS` du Cœur et les
  `allow_origins` des briques (cf. note mémoire « CORS briques autonomes »).
- **Auth brique calcul** : en multi-utilisateurs, pose `API_KEYS` sur la brique calcul et
  `CALCUL_KEY` côté Cœur (le client `core/muscle.py` envoie l'en-tête `X-API-Key`).
- **Wake-on-LAN** : fiable en LAN filaire. En WiFi/veille profonde, garde le Mac en
  « Power Nap » + privilégie le `wakeping` (le mesh maintient l'hôte joignable), ou règle
  le Mac pour ne pas s'endormir si la continuité prime sur l'économie d'énergie.

---

## Dépannage
| Symptôme | Piste |
|---|---|
| ⚙ Cerveau : « Brique calcul injoignable » | la brique calcul tourne-t-elle ? `CALCUL_URL` correct ? |
| Nœud toujours 🔴 injoignable | `netbird status` des 2 côtés ; `curl http://<ip-mesh>:11434/api/tags` depuis le Cœur |
| Réponse jamais calculée par le Mac | `modele_gateway` du nœud == un model_name réel du LiteLLM ? `MUSCLE_n_URL`/`OLLAMA_URL` recréés ? |
| Le Mac ne se réveille pas | WoL ne traverse pas le bridge Docker → `network_mode: host` (Linux) ou compter sur `wakeping` ; vérifier la MAC |
| Lenteur en 4G | normal au réveil (chargement du modèle) ; le streaming token (S60) améliorera le ressenti |
