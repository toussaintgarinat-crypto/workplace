# GUIDE — Mesh NetBird : accès distant + réveil du HP + partage de calcul

Ce guide met en place un **réseau privé chiffré** (mesh WireGuard via **NetBird**) qui relie
ton téléphone, le **HP** (Proxmox, qui héberge tout le stack Workplace) et — plus tard — un
**Mac** de calcul, **sans ouvrir le moindre port applicatif** sur la box internet.

Il sert **deux** buts d'un coup :
1. **Accès distant à la solution** : joindre le dashboard du Cœur depuis n'importe où (4G),
   comme si tu étais à la maison, sans exposer Workplace sur internet.
2. **Réveil du HP à distance** : un petit **Raspberry Pi** allumé H24 réveille le HP
   (Wake-on-LAN) quand tu en as besoin, puis le HP dort le reste du temps (économie d'énergie).

```
   📱 Téléphone (4G/5G)        🍓 Raspberry Pi 3B+ (H24, ~3W)        🖥️ HP 800 G4 (Proxmox)
   navigateur / PWA            • pair NetBird permanent               ├─ hôte Proxmox (métal)
        │                      • bouton « réveille le HP » (WoL)      └─ VM Debian 192.168.1.89
        │                                │                              stack Docker complet
        │                                │                              (Cœur + briques + Gateway)
        └───────── mesh NetBird (WireGuard, chiffré bout-en-bout) ──────────────┘
                                   ▲ aiguillé par NetBird Cloud
                        (plan de contrôle SaaS — ne voit JAMAIS le trafic)
```

> **Topologie retenue** : le **plan de contrôle** (l'« aiguilleur » qui permet aux pairs de
> se trouver et de percer les NAT) est **NetBird Cloud** (offre perso gratuite). Il ne voit
> jamais le contenu (chiffré de bout en bout entre pairs). Ce choix évite d'ouvrir le moindre
> port sur la box et d'auto-héberger un serveur de contrôle (un Pi 3B+ à 1 Go de RAM ne peut
> pas faire tourner Zitadel confortablement). Le Pi, lui, est **parfait** comme pair permanent
> + bouton d'allumage : le client NetBird pèse quelques dizaines de Mo.

> **Rappel Proxmox** : `192.168.1.89` est une **VM KVM** sur l'hôte Proxmox, pas le métal.
> Conséquences (partie D) : le Wake-on-LAN vise la **carte physique du HP** (pas la MAC de la
> VM), et la VM doit être en **« Start at boot »** pour remonter toute seule après le réveil.

---

## Partie A — NetBird Cloud : compte + clé d'enrôlement (toi)
1. Va sur **https://app.netbird.io**, crée un compte (gratuit pour un usage perso).
2. **Settings → Setup Keys → Create Setup Key** : coche **Reusable**, donne-lui un nom
   (ex. `workplace`). Copie la clé (format `XXXXXXXX-...`). C'est le seul secret à partager
   entre tes machines pour les rattacher au réseau.
3. (Optionnel mais conseillé) crée un **groupe** `workplace` pour ranger tes pairs.

> Le « management URL » par défaut du Cloud est `https://api.netbird.io` — les clients
> l'utilisent automatiquement, pas besoin de le préciser en Cloud.

---

## Partie B — Enrôler la VM du HP (accès distant) — *je peux le faire par SSH*
Sur la VM Debian (`192.168.1.89`) :

```bash
curl -fsSL https://pkgs.netbird.io/install.sh | sh
sudo netbird up --setup-key <SETUP_KEY>
netbird status        # doit afficher « Connected » + une IP mesh (100.x.y.z)
```

Note l'**IP mesh** attribuée à la VM (ex. `100.100.0.10`). Fixe/renomme-la dans le dashboard
NetBird pour qu'elle soit **stable** (« workplace-hp »).

À partir de là, l'**accès distant fonctionne déjà** : depuis un pair du mesh (ton téléphone
enrôlé en partie E), ouvre `http://<IP_MESH_VM>:5100/dashboard`. Le stack tourne déjà sur la
VM (aucun port ouvert sur la box, tout passe par le tunnel chiffré).

> Donne-moi une setup key et je déroule cette partie B en SSH sur la VM.

---

## Partie C — Le Raspberry Pi : pair permanent + bouton « réveille le HP » (toi)
Le Pi reste **allumé en permanence** (~3 W) : c'est lui qui répond quand le HP dort, et c'est
lui qui envoie le Wake-on-LAN pour réveiller le HP.

**C.1 — Enrôler le Pi dans le mesh**
```bash
# Sur le Pi (Raspberry Pi OS 64 bits conseillé)
curl -fsSL https://pkgs.netbird.io/install.sh | sh
sudo netbird up --setup-key <SETUP_KEY>
netbird status                     # « Connected » + IP mesh (ex. 100.100.0.20)
```

**C.2 — Le bouton d'allumage (réutilise la brique `calcul`)**
La brique `calcul` sait déjà envoyer le Wake-on-LAN (son `POST /noeuds/{id}/reveiller`). On la
fait tourner sur le Pi en `network_mode: host` pour que le magic packet atteigne le LAN.

```bash
# Sur le Pi : récupérer le code (le dossier briques/calcul suffit)
git clone <url-du-repo> workplace && cd workplace/briques/calcul
# Config locale du Pi :
cat > .env.pi <<'EOF'
REVEIL_NOEUDS=[{"id":"hp","nom":"HP 800 G4 (Proxmox)","endpoint":"http://<IP_MESH_VM>:5100","sondes":["/health"],"mac_wol":"<MAC_PHYSIQUE_HP>","broadcast_wol":"192.168.1.255","methode_reveil":["wol"],"reveil_timeout_s":240,"intervalle_sonde_s":5}]
REVEIL_KEY=<une-clé-secrète-de-ton-choix>
EOF
docker compose -f docker-compose.pi.yml up -d --build
curl -s http://127.0.0.1:5990/sante        # {"ok":true,...}
```

- `<IP_MESH_VM>` = l'IP mesh de la VM (partie B). `<MAC_PHYSIQUE_HP>` = partie D.
- Le fichier `docker-compose.pi.yml` est fourni dans `briques/calcul/`.
- Pas de Docker sur le Pi ? On peut lancer la brique en natif : `pip install -r requirements.txt
  && uvicorn main:app --host 0.0.0.0 --port 5990` (avec `CALCUL_NOEUDS` exporté).

**C.3 — Réveiller le HP depuis le téléphone (4G)**
```
# téléphone (4G) → mesh → Pi
curl -X POST http://<IP_MESH_PI>:5990/noeuds/hp/reveiller -H "X-API-Key: <REVEIL_KEY>"
# → envoie le WoL, attend que le Cœur réponde, verdict honnête {reveille, methode, duree_s}
```
Tu peux en faire un raccourci (Raccourcis iOS / widget) qui tape cette URL. La sonde
`/health` ne passe au vert qu'une fois le HP **complètement** remonté (Proxmox + VM + Docker).

---

## Partie D — Prérequis Wake-on-LAN du HP physique (toi, une fois)
Comme `192.168.1.89` est une **VM**, le WoL doit réveiller la **machine physique** (l'hôte
Proxmox). Trois réglages :

1. **MAC physique du HP** : sur l'hôte Proxmox (pas la VM), `ip -br link` → la carte Intel
   (souvent `eno1`/`enp0s31f6`). Sa MAC = `<MAC_PHYSIQUE_HP>` à mettre dans `REVEIL_NOEUDS`.
   ⚠️ **Pas** la MAC `bc:24:11:…` de la VM (carte virtuelle Proxmox, elle ne répond pas au WoL).
2. **BIOS du HP** : active **« Wake On LAN »** (HP 800 G4 : *Advanced → Power Management*,
   règle « After Power Loss »/« Remote Wakeup », et **désactive** le mode d'économie S5 max qui
   coupe l'alimentation de la carte réseau au repos).
3. **VM en démarrage auto** : Proxmox → la VM → *Options* → **« Start at boot » = Yes**
   (idéalement un petit *Start/Shutdown order delay*). Ainsi, réveiller l'hôte remonte la VM
   et tout le stack sans intervention.

Vérifie le WoL depuis le Pi une fois le HP éteint proprement :
```bash
docker exec reveil_hp python -c "import noeud; noeud.envoyer_wol('<MAC_PHYSIQUE_HP>','192.168.1.255')"
# le HP doit démarrer (voyant/ventilateur), puis Proxmox → VM → stack
```

---

## Partie E — Le téléphone (toi)
Installe l'app **NetBird** (iOS/Android), connecte-toi au **même** compte Cloud (ou colle la
setup key). En 4G/5G, le téléphone rejoint le mesh comme les autres. Puis :
- **Accès distant** : ouvre `http://<IP_MESH_VM>:5100/dashboard` (ou installe-le en PWA, cf.
  S61 — le dashboard est déjà « installable »).
- **Réveil** : le raccourci de la partie C.3.

---

## Partie F — Le Mac de calcul (« le Muscle ») — UNE COMMANDE

Depuis **S131**, brancher un ordinateur comme nœud de calcul ne nécessite **ni toucher au `.env`
ni recréer un conteneur** côté serveur. Le muscle s'auto-annonce à la brique calcul, qui
l'enregistre dans le Gateway toute seule.

### F.1 — La commande (colle-la sur la machine cible)

```bash
curl -fsSL https://<IP_MESH_HP>:5990/muscle/bootstrap.sh | \
  MUSCLE_KEY=<clé_api_brique_calcul> \
  CALCUL_MESH=<IP_MESH_HP>:5990 \
  SETUP_KEY=<SETUP_KEY_NETBIRD> \
  sh
```

**Ce que le script fait automatiquement :**
1. **Mesh** : si la machine n'est pas dans NetBird → installe le client et la rejoint.
2. **Runtime LLM** : détecte Ollama / LM Studio / llama.cpp déjà présent ; sinon installe
   Ollama et choisit un modèle selon la RAM (3b < 8 Go, 8b ~16 Go, 14b ~32 Go, 70b ≥ 64 Go).
3. **Inscription** : `POST /noeuds` sur la brique calcul — sonde live + persistance + enregistrement
   du modèle dans LiteLLM (Gateway).
4. **Idempotent** : relancer le script ré-inscrit le même id sans créer de doublon.

**Variables disponibles :**
| Variable | Rôle |
|---|---|
| `MUSCLE_KEY` | Clé API brique calcul (définie dans `API_KEYS` du stack) |
| `CALCUL_MESH` | `<IP_MESH_HP>:<port>` de la brique calcul |
| `SETUP_KEY` | Clé NetBird (optionnel si déjà dans le mesh) |
| `MUSCLE_MODELE` | Override le modèle choisi automatiquement |
| `MUSCLE_DRYRUN` | Si non vide : détecte + affiche le payload, n'installe rien |

**Test à blanc (dry-run, sans réseau ni install) :**
```bash
MUSCLE_KEY=test CALCUL_MESH=x:5990 MUSCLE_DRYRUN=1 sh bootstrap.sh
```

### F.2 — Vérifier l'inscription

Dans **⚙ Cerveau** du dashboard → tuile Calcul : le nouveau nœud doit apparaître 🟢.
Le modèle du muscle est visible dans LiteLLM et tombe en tête de cascade du Cœur
(vérifie `modele_utilise` dans le journal d'usage).

> **MUSCLE_KEY** : définie dans l'env de la brique calcul (`API_KEYS` dans `briques/calcul/.env`
> ou dans le `.env` racine du stack). Elle sera demandée à l'exécution du script, jamais
> stockée sur le serveur.

> Note : la brique `calcul` du **stack** (parc = les Muscles LLM) est distincte d'une
> éventuelle instance `calcul` sur le **Pi** (parc = le HP à réveiller). Deux rôles distincts.

---

### Annexe F — Repli manuel (si le script ne convient pas)

Si tu préfères contrôler chaque étape à la main :

```bash
# 1. Enrôler dans le mesh
curl -fsSL https://pkgs.netbird.io/install.sh | sh
sudo netbird up --setup-key <SETUP_KEY>

# 2. Servir un LLM OpenAI-compatible
OLLAMA_HOST=0.0.0.0:11434 ollama serve
ollama pull llama3.3

# 3. S'inscrire auprès de la brique calcul (X-API-Key = MUSCLE_KEY du stack)
curl -X POST https://<IP_MESH_HP>:5990/muscle/noeuds \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <MUSCLE_KEY>" \
  -d '{
    "id": "mac-bureau",
    "nom": "Mac Bureau",
    "endpoint": "http://<IP_MESH_MAC>:11434",
    "modele": "llama3.3",
    "methode_reveil": ["wakeping"],
    "priorite": 10
  }'
```

Le nœud est persisté sur disque côté serveur et survivra aux redémarrages de la brique
(plus besoin de modifier `CALCUL_NOEUDS` dans le `.env`).

---

## Durcissement
- **Aucun port applicatif mappé vers l'extérieur de la box** : le dashboard (5100), la Gateway,
  Ollama (11434) ne doivent être joignables **que par le mesh**. NetBird Cloud n'expose rien
  côté box ; garde-le ainsi (pas de redirection de port « au cas où »).
- **Bouton de réveil protégé** : pose `REVEIL_KEY` (partie C.2) → seul qui a la clé peut
  réveiller le HP. En multi-utilisateur, fais de même sur la brique calcul du stack (`API_KEYS`
  + `CALCUL_KEY` côté Cœur, le client `core/muscle.py` envoie `X-API-Key`).
- **Access control NetBird** : dans le dashboard Cloud, restreins les *policies* pour que seuls
  tes pairs (téléphone/Pi/HP/Mac) se voient, et supprime les setup keys inutiles après usage.
- **CORS** : si tu exposes un front hors iframe, resserre `CORS_ORIGINS` du Cœur et des briques
  (cf. note « CORS briques autonomes »).

---

## Limites honnêtes
- **Accès distant partiel** : le dashboard du Cœur + le chat (streaming S60) marchent via l'IP
  mesh. Mais certaines **iframes de briques** et le **WebSocket voix** pointent vers des URLs
  internes (localhost/host.docker.internal) qui ne se résolvent pas depuis le téléphone — à
  reprendre si tu veux l'expérience complète à distance (chantier séparé).
- **Preuve LIVE finale** : compte + Pi + BIOS + Mac sont à dérouler sur **ton** matériel ; le
  dépôt fournit tout le câblage (brique calcul, compose Pi, entrées Gateway, env).

---

## Dépannage
| Symptôme | Piste |
|---|---|
| Téléphone ne joint pas le dashboard | `netbird status` des 2 côtés = « Connected » ? bon `<IP_MESH_VM>` ? le HP est-il réveillé/remonté ? |
| `POST /noeuds/hp/reveiller` → `reveille:false` | WoL envoyé mais le Cœur ne répond pas à temps : MAC physique correcte ? BIOS WoL activé ? VM en « Start at boot » ? augmente `reveil_timeout_s`. |
| Le HP ne démarre pas du tout au WoL | mauvaise MAC (VM au lieu du métal), WoL désactivé au BIOS, ou `network_mode: host` absent sur le Pi (le broadcast n'atteint pas le LAN). |
| WoL ok mais la sonde reste rouge | la VM ne remonte pas (« Start at boot » ?) ou NetBird ne se relance pas dans la VM au boot (`systemctl enable netbird`). |
| Nœud Muscle (Mac) toujours 🔴 | `netbird status` ; `curl http://<IP_MESH_MAC>:11434/api/tags` depuis la VM ; `modele_gateway` == un model_name réel du LiteLLM ? |
