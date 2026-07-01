# Décision — Accès distant & partage de calcul via le mesh NetBird

- **Date** : 2026-07-01
- **Statut** : ✅ Adopté et déployé (accès distant iPhone prouvé en 5G)
- **Portée** : accès distant à la solution + fondation du partage de puissance de calcul
- **Fichiers liés** : `GUIDE-mesh-netbird.md` (ops pas-à-pas), `outils/mesh-https/` (HTTPS),
  `briques/calcul/docker-compose.pi.yml` (réveil du HP)

> **But de ce document** : pouvoir **y revenir facilement** — comprendre *pourquoi* c'est
> fait ainsi, *comment ajouter un appareil*, et *quand / comment changer d'approche* le jour
> où il y aura beaucoup d'appareils ou d'autres applications.

---

## En bref (l'état actuel)
- Réseau privé chiffré **NetBird** (WireGuard) relie mes appareils au HP, **sans ouvrir un
  seul port sur la box**.
- **Plan de contrôle = NetBird Cloud** (offre perso gratuite) — ne voit jamais le trafic.
- Le **HP** (VM Debian `192.168.1.89`) est un pair du mesh → **IP mesh `100.124.248.226`**.
- Un **Caddy** sur la VM sert le dashboard en **HTTPS** sur l'IP mesh (Safari force le https).
- Choix « **zéro dette** » : on **installe la CA locale de Caddy sur l'appareil** plutôt que
  d'utiliser un service de domaine tiers. Résultat : zéro avertissement, zéro coût, souverain.
- Accès : **`https://100.124.248.226/dashboard`**.

**Valeurs qui ont guidé le choix** : souveraineté (rien chez un tiers si évitable), coût nul,
et « pas de dette molle » tant qu'un seul appareil suffit.

---

## Contexte & objectif
Deux besoins :
1. **Accès distant** au dashboard du Cœur depuis le téléphone (4G/5G), sans exposer Workplace
   sur internet.
2. **Partage de puissance de calcul** (« le Muscle », brique `calcul`) — même réseau privé.

Contraintes : box internet domestique (pas d'IP publique fixe exploitée, pas de port ouvert
voulu), HP en **VM Proxmox** (le métal peut dormir), un seul utilisateur aujourd'hui mais
**multi-appareils / multi-utilisateurs à terme**.

---

## Décision
### 1. Topologie réseau : NetBird Cloud + pairs
- Plan de contrôle **NetBird Cloud** (SaaS gratuit perso), pas auto-hébergé.
  - *Pourquoi pas auto-hébergé ?* Le seul « toujours allumé » dispo est un **Raspberry Pi 3B+
    (1 Go RAM)** qui **ne peut pas** faire tourner Zitadel/management confortablement. Et le
    Cloud évite d'ouvrir des ports de contrôle sur la box.
  - *Souveraineté ?* Acceptable : le Cloud n'est qu'un **aiguilleur** ; le trafic est chiffré
    **de bout en bout** entre pairs, il ne le voit jamais.
- Le **HP (VM)** = pair permanent → accès distant.
- Un **Raspberry Pi** (à venir) = pair permanent H24 + **bouton de réveil** du HP (Wake-on-LAN).

### 2. HTTPS : terminaison Caddy + CA installée sur l'appareil
- Safari (iOS) **force `https://`** ; le Cœur ne parle que HTTP sur `:5100`. Un **Caddy** sur
  la VM termine le TLS sur l'IP mesh et proxifie le Cœur.
- Certificat : **CA interne de Caddy** (`tls internal`), **installée et approuvée sur
  l'iPhone**. Pas de DuckDNS, pas de domaine payant.
  - *Pourquoi ?* Un seul appareil + souveraineté → installer la CA une fois = **zéro
    avertissement, zéro service tiers, zéro coût**. C'est l'option **sans dette**.

---

## Alternatives considérées & quand basculer
| Approche | Coût | Dépendance externe | Avertissement navigateur | Bon quand… |
|---|---|---|---|---|
| **CA locale installée sur l'appareil** *(choisi)* | 0 | aucune | non | peu d'appareils, souveraineté |
| Avertissement 1-tap (sans installer la CA) | 0 | aucune | oui (1 tap) | test rapide, appareil de passage |
| **DuckDNS + Let's Encrypt** (DNS-01) | 0 | DuckDNS (molle) | non | **beaucoup d'appareils** (installer la CA sur chacun devient pénible) |
| **Vrai domaine payant** (Cloudflare, etc.) | ~10 €/an | ton registrar | non | multi-utilisateurs, cloud, image « pro » |
| Auto-héberger le plan de contrôle NetBird | VPS/gros nœud | toi-même | — | souveraineté totale du contrôle, machine costaude dispo |

**Déclencheurs de bascule (à surveiller)** :
- **> ~3-4 appareils** ou des appareils que tu ne contrôles pas (invités, clients) →
  passe à **DuckDNS** (tout est déjà prêt, voir runbook C) ou à un **vrai domaine**.
- **Multi-utilisateurs / mise en cloud** → **vrai domaine** + éventuellement plan de contrôle
  NetBird auto-hébergé sur une machine costaude.
- **DuckDNS te gêne** (souveraineté) mais tu veux zéro avertissement multi-appareils →
  **vrai domaine que tu contrôles** (DNS-01 chez ton registrar).

Tout le nécessaire pour DuckDNS est **déjà versionné** (`outils/mesh-https/Caddyfile.duckdns`,
`Dockerfile.duckdns`, `docker-compose.duckdns.yml`) → la bascule est un changement de config,
pas une réécriture.

---

## État déployé (concret)
| Élément | Valeur |
|---|---|
| Compte plan de contrôle | NetBird Cloud (app.netbird.io) |
| Pair HP (VM Debian) | `100.124.248.226` (`debian.netbird.cloud`) |
| Pair iPhone | `100.124.158.27` |
| Service NetBird VM | systemd `netbird`, `enabled` (reconnexion au boot) |
| Caddy (VM) | `~/mesh-https/` sur la VM, image `caddy:2`, `network_mode: host`, port 443 |
| CA racine (empreinte SHA256) | `3A:2E:5C:8E:70:1F:94:AF:6D:5B:2C:46:48:F9:C0:A9:DC:9E:40:9D:D9:BD:06:2F:5B:C6:1D:B8:96:48:27:36` |
| URL dashboard distant | `https://100.124.248.226/dashboard` |
| URL du certificat à installer | `https://100.124.248.226/rootca.crt` |
| Config versionnée | branche `feat/netbird-mesh-acces-distant` (`80e197b`, `2a827a4`, `8d272ef`) |

Accès SSH VM : `ssh debian@192.168.1.89` (cf. mémoire HP). Fichiers Caddy sur la VM :
`~/mesh-https/Caddyfile` + `~/mesh-https/docker-compose.yml`.

---

## Runbooks (comment revenir dessus)

### A. Ajouter un nouvel appareil au mesh (tél, laptop…)
1. Récupère/crée une **setup key réutilisable** dans app.netbird.io (Settings → Setup Keys).
2. Installe le client NetBird sur l'appareil (app iOS/Android, ou
   `curl -fsSL https://pkgs.netbird.io/install.sh | sh && sudo netbird up --setup-key <KEY>`).
3. `netbird status` → « Connected » + une IP mesh. L'accès distant marche aussitôt.

### B. Zéro avertissement sur ce nouvel appareil (installer la CA)
1. Ouvre `https://100.124.248.226/rootca.crt` (contourne l'avertissement une fois pour
   télécharger).
2. Installe le profil (iOS : Réglages → profil téléchargé → Installer).
3. **iOS uniquement, l'étape oubliée** : Réglages → Général → Informations → *Réglages de
   confiance des certificats* → active « Caddy Local Authority ». (macOS : Trousseau → faire
   confiance ; Android : Paramètres → Sécurité → certificat CA.)
4. Vérifie l'empreinte (tableau ci-dessus) avant d'approuver.

### C. Basculer vers DuckDNS (zéro avertissement, multi-appareils, gratuit)
1. Compte sur duckdns.org → sous-domaine (ex. `monworkplace`) + token.
2. Pointe le nom sur l'IP mesh :
   `curl "https://www.duckdns.org/update?domains=monworkplace&token=<TOKEN>&ip=100.124.248.226"`
3. Sur la VM, dans `~/mesh-https/` : adapte `Caddyfile.duckdns` (nom + email), `cp` vers
   `Caddyfile`, `echo DUCKDNS_TOKEN=<TOKEN> > .env`,
   `docker compose -f docker-compose.duckdns.yml up -d --build`.
4. Accès : `https://monworkplace.duckdns.org/dashboard`. (Détails : `outils/mesh-https/README.md`.)

### D. Réutiliser ce schéma pour une AUTRE application
Le motif est générique : **NetBird (mesh) + Caddy (HTTPS sur IP mesh) + reverse_proxy vers
le service interne**. Pour une nouvelle app servie en HTTP sur `localhost:<PORT>` de la VM :
- Ajoute un bloc dans le `Caddyfile` (même IP, sous-chemin) **ou** un 2ᵉ site/port, p. ex.
  `handle_path /monapp/* { reverse_proxy localhost:<PORT> }`.
- Si l'app est sur une **autre machine**, enrôle-la dans le mesh (runbook A) et
  `reverse_proxy <IP_MESH_MACHINE>:<PORT>`.
- Aucune ouverture de port sur la box : tout transite par le mesh chiffré.

### E. Réveil du HP à distance (Raspberry Pi) — à faire plus tard
Voir `GUIDE-mesh-netbird.md` parties C & D. Résumé : le Pi (pair H24) fait tourner la brique
`calcul` (`briques/calcul/docker-compose.pi.yml`, `network_mode: host`) ; un
`POST http://<IP_MESH_PI>:5990/noeuds/hp/reveiller` envoie le Wake-on-LAN à la **carte
physique du HP** (pas la VM). Prérequis : MAC physique, WoL au BIOS, VM en « Start at boot ».

---

## Limites connues
- **Iframes de briques** : ~~pointaient vers des URLs internes non résolues depuis le
  téléphone~~ → **RÉSOLU + DÉPLOYÉ + PROUVÉ LIVE (11/11 briques HTTPS sur le mesh, LAN non
  régressé)** par S128 (`docs/sprints/S128-briques-embarquees-acces-distant.md`) :
  les URLs d'iframe sont construites depuis le scheme + l'hôte de la requête
  (`core/urls_ui.url_brique`) et Caddy expose chaque brique en HTTPS sur son port
  (`outils/mesh-https/Caddyfile.briques`). Restent **différés** : Forge (SSO Keycloak) et
  l'IDE dev (code-server). **Preuve LIVE** (dashboard distant + tuiles) à faire depuis un pair
  du mesh. Déploiement HP : **retirer les surcharges `<NOM>_UI_URL=192.168.1.89:…`** +
  **poser `MESH_HOST=100.124.248.226`** dans `core/docker-compose.override.yml`. Caddy expose
  chaque brique en HTTPS sur un **port décalé (+10000)** — les briques gardent `0.0.0.0` (leur
  port réel est déjà pris sur l'IP mesh, d'où le décalage), donc rien à recréer côté briques.
- **NetBird Cloud** : dépendance à un tiers pour l'aiguillage (pas pour le trafic). Repli
  possible = auto-héberger le plan de contrôle sur une machine costaude le jour venu.
- **CA locale** : à installer sur **chaque** appareil (d'où la bascule DuckDNS/domaine quand
  ils se multiplient).

---

## Références
- `GUIDE-mesh-netbird.md` — ops pas-à-pas (compte, enrôlement, Pi, WoL, Mac muscle).
- `outils/mesh-https/` — Caddy (variante CA interne active + variante DuckDNS prête) + README.
- `briques/calcul/` — « le Muscle » + `docker-compose.pi.yml` (bouton réveil du HP).
- Roadmap déploiement multi-utilisateur (mono → Proxmox → multi → cloud).
