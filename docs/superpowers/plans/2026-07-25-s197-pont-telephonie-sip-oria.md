# S197 — Pont téléphonie SIP/PSTN ↔ Oria (roomkit-visio) — Plan de faisabilité + Phase 1

> **For agentic workers:** ce plan n'est PAS un plan de code applicatif classique. Phase 0 (ce
> document) est un livrable de recherche — il n'y a rien à « exécuter » pour Phase 0, elle est
> déjà faite. **Seule la Phase 1 contient des tâches à cocher.** Utilise
> superpowers:subagent-driven-development ou superpowers:executing-plans pour dérouler les
> tâches de Phase 1 — **jamais sans repasser par un humain avant chaque étape qui touche à
> l'exposition réseau ou à un compte tiers (OVH)**. Aucune tâche de ce plan, y compris en
> Phase 1, ne suppose ou ne nécessite un compte OVH actif.

**Objectif produit** : évaluer si `roomkit-visio` (suitenumerique/roomkit-visio, MIT) —
Kamailio + rtpengine + `livekit-sip` (fork `suitenumerique/livekit-sip`, branche `sip-video`,
Apache-2.0) — peut faire atterrir un vrai numéro de téléphone français directement dans une
room LiveKit d'Oria, pour compléter (pas forcément remplacer) `briques/telephonie` (SMS+voix
Twilio, port 6050) qui ne fait aujourd'hui aucun pont vers Oria.

**Architecture (si Phase 2 va au bout)** : SIP/PSTN (OVH trunk) → Kamailio (proxy/dispatch,
`network_mode: host`) → rtpengine (relais RTP/RTCP + SDES AES-128, `network_mode: host`) →
`livekit-sip` (traduction SIP↔LiveKit, transcodage G.711/G.722↔Opus + GStreamer H.264↔VP8/VP9)
→ LiveKit server d'Oria (déjà en place, `oria-stack/oria/docker-compose.yml`, image
`livekit/livekit-server:v1.12.0`, ports hôte 7880/7881/7882). Postgres dédié pour l'état
Kamailio (subscriber/dispatcher/rtpengine/uacreg). Monitoring Prometheus/Grafana optionnel.

**Tech stack** : Kamailio 6.0.3, `audiocodes/rtpengine:13.5.1.3-2`, `livekit-sip:local` (Go
1.25 + GStreamer 1.28.1, buildé localement — pas d'image publiée), Postgres 16, Docker Compose.

## Global Constraints

- **Aucun code n'est écrit par ce plan.** Ce document ne fait ni commit ni modification de
  fichier — c'est le contrat demandé pour ce sprint (S197 = feasibility + scaffolding Phase 1
  prêt à exécuter, pas « codé et livré » comme un sprint brique classique).
- **Aucune tâche ne modifie `briques/telephonie/`** (SMS+voix Twilio existant) — ce chantier
  vit à côté, dans un nouveau dossier `sip-stack/roomkit-visio/` (miroir du motif déjà en place
  pour `oria-stack/oria/` : un stack externe vendoré, pas une « brique » manifest.json au sens
  strict de `GUIDE-ajouter-une-brique.md`, comme Oria elle-même n'en est pas une — sa fine
  pellicule `briques/oria/` est un proxy séparé).
- **Aucune tâche de Phase 1 n'ouvre de port vers Internet** ni ne touche à un pare-feu/routeur
  physique — tout reste LAN/mesh NetBird.
- **Aucune tâche ne suppose un abonnement OVH actif** — la ligne `uacreg` reste désactivée
  (`auth_password` vide) partout dans ce plan.
- **Hôte cible = le HP** (`debian@192.168.1.89`, cf. mémoire `hp-ssh`/`hpworkplace`), **jamais
  le Mac** — raison détaillée au risque n°3 ci-dessous.
- Les deux dépôts sources amont ne sont **pas commités tels quels** : `roomkit-visio` (config
  d'orchestration, à adapter) est vendoré dans `sip-stack/roomkit-visio/` ; `livekit-sip` (code
  Go+GStreamer non modifié, buildé en local) reste un **clone externe non commité**, gitignoré,
  au même motif que `node_modules` (déjà dans `.gitignore` du repo).

---

## Risques / Décisions à trancher (à lire AVANT toute exécution de Phase 1)

Ces points ne sont **pas** tranchés dans ce plan — ils appartiennent à l'utilisateur.

1. **Coût + engagement OVH (LA décision qui n'appartient qu'à l'utilisateur).** Recherche faite
   le 2026-07-25 sur `ovhcloud.com/fr/phone/sip-trunk/` (page marketing, **pas un devis
   contractuel** — chiffres à re-vérifier avant toute souscription) :
   - Formule « à la conso » : **≈ 4 €HT/mois par canal** + appels sortants facturés à la minute.
   - Formule « illimité » : **≈ 20 €HT/mois par canal** (fixes + mobiles sortants inclus).
   - Frais de mise en service : **≈ 12 €TTC**.
   - Jusqu'à 100 canaux, **« sans engagement »** annoncé par OVH pour le Trunk lui-même.
   - **Numéro géographique français** (existant à porter, ou nouveau à louer) : tarif **non
     trouvé de façon fiable** dans cette recherche — probablement quelques €/mois en plus,
     à demander en devis direct OVH avant de décider.
   - Ce plan ne souscrit rien. Phase 1 (ci-dessous) ne nécessite **aucun** compte OVH.

2. **Exposition réseau (Phase 2 uniquement, pas dans ce plan).** Un vrai trunk OVH exige des
   ports SIP/RTP **joignables depuis Internet** : `5060/udp+tcp` (SIP), `5061/tcp` (SIP/TLS),
   `5080/udp+tcp` (livekit-sip), `20301-20400/udp` (RTP rtpengine), `30001-30100/udp` (RTP
   livekit-sip). C'est une vraie surface d'attaque (scan/fraude toll classique sur SIP) — la
   whitelist `address` de Kamailio doit alors restreindre strictement aux IP du trunk OVH
   (jamais `0.0.0.0/0`). Décision d'ouverture = utilisateur, pas ce plan.

3. **Choix de l'hôte : le HP, pas le Mac.** `kamailio`, `rtpengine`, `livekit-sip` et le stack
   de monitoring tournent en `network_mode: host` dans le compose amont (voir
   `compose.yml`/`docs/networking.md` du dépôt). Sous Linux (le HP, Debian), c'est natif et
   conforme au design amont. Sous macOS avec Docker Desktop, `network_mode: host` n'expose pas
   une vraie interface réseau hôte de la même façon (support partiel/expérimental derrière un
   flag) — Kamailio et rtpengine annonceraient une IP incorrecte dans les en-têtes SIP/SDP, et
   le NAT traversal (RTP) ne fonctionnerait pas de façon fiable. **Toute la Phase 1 est donc
   écrite pour tourner en SSH sur le HP**, pas en local sur ce Mac.

4. **Build local obligatoire de `livekit-sip`.** Pas d'image publiée : Go 1.25 + GStreamer
   1.28.1 compilés dans l'image Docker depuis le fork `suitenumerique/livekit-sip@sip-video`
   (confirmé : `build/sip/Dockerfile` existe dans ce fork, deux étapes — build Go puis image
   d'exécution avec `libopus0 libopusfile0 libsoxr0`). Le HP est un i7-8700 **sans GPU dédié** —
   le transcodage vidéo H.264↔VP8/VP9 se fera en logiciel (CPU). Non-sujet en Phase 1 (un seul
   softphone de test) ; à surveiller si Phase 2 amène plusieurs appels vidéo simultanés.

5. **Règle de dispatch SIP côté LiveKit — étape manquante du README amont.** Confirmé en lisant
   le code du fork (`pkg/service/psrpc.go` : appel `EvaluateSIPDispatchRules` ;
   `pkg/sip/inbound.go` lignes ~927-1128 : `disp.DispatchRuleID`, `disp.Room.RoomName`) —
   `livekit-sip` **ne route vers aucune room** tant qu'un **SIP Trunk entrant** + une **Dispatch
   Rule** ne sont pas créés côté serveur LiveKit (API/CLI `lk sip ...`, PAS dans Kamailio/SQL).
   Le README de `roomkit-visio` dit juste « dial `555` » sans expliquer cette étape — vraisemblablement
   déjà en place dans l'environnement de démo de l'éditeur. **Tâche 6 de ce plan couvre ce trou.**

6. **Redis : le stack Oria ne l'expose pas à l'hôte (choix de sécurité déjà en place, à ne pas
   défaire).** `docker/livekit-sip/config/livekit-sip.yaml` amont attend `redis: address:
   localhost:16379` (le redis de « meet », republié sur l'hôte). Vérifié dans
   `oria-stack/oria/docker-compose.yml` : le service `redis` **n'a aucun `ports:`** — donc pas
   joignable en `localhost:<port>` depuis un autre compose. **Ne pas** republier le redis
   d'Oria vers l'hôte pour ce chantier (reculerait sur un choix de sécurité existant). L'adaptation
   retenue (Tâche 2) : sortir `livekit-sip` de `network_mode: host` et le faire rejoindre le
   réseau Docker d'Oria en pont, où `redis:6379` et `livekit:7880` sont déjà résolvables par nom
   de service — Kamailio/rtpengine, eux, restent en `network_mode: host` (ils en ont besoin
   pour annoncer la vraie IP LAN au softphone).
7. **Licences** : `roomkit-visio` = MIT (DINUM/Etalab) ; fork `livekit-sip` = Apache-2.0.
   Aucun blocage pour vendorer/adapter dans Workplace.
8. **Ce plan ne tranche PAS** « ce pont remplace-t-il Twilio pour la voix, ou vient-il en
   plus ? » — cette décision produit se prend **après** la preuve Phase 1 (softphone → room
   Oria), pas avant. `briques/telephonie` n'est touchée par aucune tâche ici.

---

## Phase 0 — Recherche / faisabilité (livrée par ce document, 2026-07-25)

Fait pendant l'écriture de ce plan (pas une tâche à refaire) :

- **Cloné et lu en détail** `suitenumerique/roomkit-visio` (`compose.yml`, `docs/architecture.md`,
  `docs/networking.md`, `docs/kamailio.md`, `docs/postgres.md`, `docs/troubleshooting.md`,
  `docs/livekit-sip-dev.md`, `docker/postgres/initdb/*`, `docker/livekit-sip/config/livekit-sip.yaml`,
  `Makefile`, `.env.example`).
- **Cloné et grep** `suitenumerique/livekit-sip@sip-video` (`pkg/sip/inbound.go`,
  `pkg/service/psrpc.go`, `build/sip/Dockerfile`) pour confirmer le mécanisme de dispatch rule
  (risque n°5) et le contenu exact du Dockerfile de build.
- **Vérifié qu'il n'y a aucune collision de port** entre `roomkit-visio`
  (5060/5061/5080/2049/22222/25432/9101/9190/3001/3100) et les briques Workplace existantes
  (`grep` sur tous les `manifest.json` — 4001 à 8400, aucun chevauchement).
- **Vérifié la topologie LiveKit existante d'Oria** : `oria-stack/oria/docker-compose.yml`
  (service `livekit`, image `v1.12.0`, ports hôte `7880/7881/7882`, config
  `oria-stack/oria/livekit/livekit.yaml`) — déjà joignable depuis l'hôte, donc `ws_url` de
  `livekit-sip` peut pointer dessus **sans modifier le compose d'Oria**.
- **Vérifié que le redis d'Oria n'est pas exposé à l'hôte** (risque n°6) — implique une
  adaptation réseau plutôt qu'un simple copier-coller du `.env.example` amont.
- **Recherche tarifaire OVH Trunk SIP** (risque n°1) — chiffres indicatifs recueillis, pas un
  devis contractuel.
- **Vérifié les licences** des deux dépôts (MIT + Apache-2.0).
- **Confirmé le numéro de sprint libre** : dernier sprint documenté = S194
  (`docs/superpowers/plans/2026-07-22-s194-brique-export-pdf-pptx.md`) → S197 ne collisionne
  avec rien d'existant dans `docs/`.

Conclusion Phase 0 : **faisable techniquement sans compte OVH** pour valider l'intégration
SIP↔LiveKit↔Oria en local (Phase 1). Le seul point dur non documenté par l'amont est la
création manuelle de la dispatch rule LiveKit (risque n°5) — couvert en Tâche 6.

---

## Phase 1 — Dev local sans PSTN réel (softphone de test, SSH sur le HP)

Objectif de la Phase 1 : prouver que `roomkit-visio` + `livekit-sip` (buildé en local) peuvent
faire entrer un appel SIP **de test** (softphone LAN, pas un vrai numéro) dans une room LiveKit
d'Oria, avec audio (et vidéo si le temps le permet) qui apparaît bien côté Oria. Zéro dépendance
OVH, zéro exposition Internet.

### Tâche 1 — Scaffold : vendorer `roomkit-visio`, gitignorer `livekit-sip`

**Fichiers :**
- Créer : `sip-stack/roomkit-visio/` (copie de travail du dépôt amont, sans son `.git/`)
- Modifier : `.gitignore` (ajouter l'entrée pour le clone `livekit-sip`)
- Créer : `sip-stack/README.md` (note de provenance + commandes de clonage)

**Étapes :**

- [ ] **Étape 1 : sur le HP, cloner `roomkit-visio` en copie de travail (pas de sous-module)**

```bash
ssh debian@192.168.1.89
cd ~/workplace
mkdir -p sip-stack
git clone --depth 1 https://github.com/suitenumerique/roomkit-visio.git /tmp/roomkit-visio-src
rsync -a --exclude='.git' /tmp/roomkit-visio-src/ sip-stack/roomkit-visio/
rm -rf /tmp/roomkit-visio-src
```

- [ ] **Étape 2 : ajouter l'entrée gitignore pour `livekit-sip` (clone externe, jamais commité)**

Ajouter dans `.gitignore`, à la suite du bloc existant `**/node_modules` / `**/venv` :

```gitignore
# S197 — livekit-sip est un fork Go+GStreamer buildé en local depuis
# suitenumerique/livekit-sip@sip-video ; code non modifié par Workplace, jamais commité
# (même motif que node_modules) — voir sip-stack/README.md pour la commande de clonage.
sip-stack/livekit-sip/
```

- [ ] **Étape 3 : écrire `sip-stack/README.md`**

```markdown
# sip-stack — pont téléphonie SIP/PSTN ↔ Oria (S197)

Vendoré depuis [suitenumerique/roomkit-visio](https://github.com/suitenumerique/roomkit-visio)
(MIT), adapté pour se brancher sur le LiveKit **déjà présent** dans `oria-stack/oria/`
(pas de dépôt « meet » séparé — chez suitenumerique, `roomkit-visio` est prévu pour tourner à
côté de leur projet `meet` ; chez Workplace, Oria joue ce rôle : LiveKit + redis + auth).

## Prérequis (Phase 1 — dev local, PAS de PSTN réel)

Cloner le fork `livekit-sip` (Apache-2.0) à côté — **non commité** (voir `.gitignore`) :

```bash
git clone -b sip-video https://github.com/suitenumerique/livekit-sip.git sip-stack/livekit-sip
```

## Ce qui a été adapté par rapport à l'amont

- `compose.yml` : `livekit-sip` rejoint le réseau Docker d'Oria (`oria_default` — à confirmer
  avec `docker network ls | grep oria`) au lieu de `network_mode: host`, pour joindre
  `redis:6379` et `livekit:7880` sans republier le redis d'Oria vers l'hôte.
  `kamailio`/`rtpengine` restent en `network_mode: host` (annoncent la vraie IP LAN au
  softphone, conforme au design amont).
- `.env` : `MY_IP_ADDR` = IP LAN du HP (pas 192.168.0.10 par défaut).
- `docker/livekit-sip/config/livekit-sip.yaml` : `ws_url`/`api_key`/`api_secret` alignés sur
  `oria-stack/oria/.env` (`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`) plutôt que sur les valeurs de
  dev amont (`devkey`/`secret`).
- `docker/postgres/initdb/02_insert_data_dev.sh` : ligne `uacreg` (OVH) **laissée désactivée**
  (`auth_password=''`) — aucun compte OVH en Phase 1.

## Ne pas faire en Phase 1

- Ne pas exposer 5060/5061/5080/RTP vers Internet.
- Ne pas remplir `uacreg` avec de vrais identifiants OVH.
- Ne pas toucher à `briques/telephonie/` ni à `oria-stack/oria/docker-compose.yml`.
```

- [ ] **Étape 4 : commit du scaffold (README + gitignore seulement — pas encore le vendoring lourd)**

À ce stade, ne committer QUE `.gitignore` et `sip-stack/README.md` (pas encore
`sip-stack/roomkit-visio/`, qui sera commité une fois adapté en Tâche 2, pour éviter un commit
« vendoring brut puis modifs » qui double l'historique). Vérifier d'abord que rien
d'inattendu n'a été copié :

```bash
cd ~/workplace && git status sip-stack/
git add .gitignore sip-stack/README.md
git commit -m "chore(sip-stack): scaffold pont téléphonie SIP↔Oria — recherche S197"
```

---

### Tâche 2 — Adapter `compose.yml` : réseau Oria, clés LiveKit, redis

**Fichiers :**
- Créer : `sip-stack/roomkit-visio/compose.override.yml` (surcouche — ne pas modifier
  `compose.yml` amont directement, pour rester facile à re-synchroniser avec l'amont plus tard)

**Interfaces :**
- Consomme : réseau Docker d'Oria déjà créé par `oria-stack/oria/docker-compose.yml` (nom par
  défaut Compose = `oria_default`, **à confirmer** sur le HP avant d'écrire le fichier final :
  `docker network ls | grep oria`).
- Produit : `livekit-sip` joignable par Kamailio sur `${MY_IP_ADDR}:5080` (publié en bridge,
  pas host) ; `livekit-sip` joint `redis:6379` et `livekit:7880` par nom de service Oria.

- [ ] **Étape 1 : confirmer le nom du réseau Docker d'Oria sur le HP**

```bash
ssh debian@192.168.1.89 "docker network ls | grep -i oria"
```
Attendu : une ligne du type `oria_default` (ou `oria-stack_default` selon le nom du dossier vu
par Compose — **utiliser la valeur réelle retournée ici**, pas une supposition).

- [ ] **Étape 2 : écrire `sip-stack/roomkit-visio/compose.override.yml`**

```yaml
# Surcouche Workplace (S197) — NE PAS fusionner dans compose.yml amont (facilite le
# resynchronisation avec suitenumerique/roomkit-visio plus tard).
#
# Sort livekit-sip de network_mode: host pour qu'il rejoigne le réseau Docker d'Oria en
# bridge (résout `redis` et `livekit` par nom de service) — cf. risque n°6 du plan S197.
# Kamailio/rtpengine restent en network_mode: host (annoncent la vraie IP LAN, requis pour
# le NAT traversal RTP avec un softphone réel sur le LAN).
services:
  livekit-sip:
    network_mode: !reset null        # annule le `network_mode: host` du compose.yml amont
    networks:
      - default                      # réseau propre à roomkit-visio (postgres-kamailio dessus)
      - oria_net                     # réseau d'Oria — REMPLACER "oria_net" par le nom réel
                                      # trouvé à l'Étape 1 (ex. oria_default)
    ports:
      - "5080:5080/tcp"
      - "5080:5080/udp"
      - "9101:9101/tcp"
      - "30001-30100:30001-30100/udp"
    environment:
      SIP_LISTEN: "udp:0.0.0.0:5080,tcp:0.0.0.0:5080"
      SIP_EXTERNAL_ADDR: ${MY_IP_ADDR:-192.168.1.89}

networks:
  oria_net:
    external: true
    name: oria_net   # REMPLACER par le nom réel confirmé à l'Étape 1
```

- [ ] **Étape 3 : adapter `docker/livekit-sip/config/livekit-sip.yaml` (redis + LiveKit au nom
  de service Oria, plus `localhost`)**

Remplacer dans `sip-stack/roomkit-visio/docker/livekit-sip/config/livekit-sip.yaml` :

```yaml
redis:
  address: localhost:16379
```
par :
```yaml
redis:
  address: redis:6379     # nom de service sur le réseau Docker d'Oria (oria_net), pas l'hôte
```

et remplacer :
```yaml
livekit:
api_key: devkey
api_secret: secret
ws_url: "ws://localhost:7880"
insecure: true
```
par :
```yaml
livekit:
  api_key: ${ORIA_LIVEKIT_API_KEY}      # = LIVEKIT_API_KEY de oria-stack/oria/.env
  api_secret: ${ORIA_LIVEKIT_API_SECRET} # = LIVEKIT_API_SECRET de oria-stack/oria/.env
  ws_url: "ws://livekit:7880"            # nom de service Oria, pas localhost
  insecure: true                          # OK en LAN de test ; à revoir en Phase 2
```
Ces deux variables (`ORIA_LIVEKIT_API_KEY`/`ORIA_LIVEKIT_API_SECRET`) sont lues depuis
`sip-stack/roomkit-visio/.env`, copiées **manuellement** (pas de secret partagé automatiquement
entre les deux stacks) depuis `oria-stack/oria/.env` :

```bash
grep -E '^LIVEKIT_API_(KEY|SECRET)=' ~/workplace/oria-stack/oria/.env
```

- [ ] **Étape 4 : vérifier que la config YAML reste valide (pas de commit tant que ce n'est pas
  vérifié — étape manuelle, pas de test automatisé pour un fichier YAML de conf tierce)**

```bash
cd ~/workplace/sip-stack/roomkit-visio
docker run --rm -v "$PWD/docker/livekit-sip/config/livekit-sip.yaml:/tmp/c.yaml" \
  python:3.12-slim python -c "import yaml; yaml.safe_load(open('/tmp/c.yaml'))" && echo "YAML OK"
```
Attendu : `YAML OK`.

- [ ] **Étape 5 : commit**

```bash
cd ~/workplace
git add sip-stack/roomkit-visio/compose.override.yml \
        sip-stack/roomkit-visio/docker/livekit-sip/config/livekit-sip.yaml
git commit -m "chore(sip-stack): adapte livekit-sip au réseau Docker d'Oria (S197)"
```

---

### Tâche 3 — `.env`, certs TLS, seed Postgres Kamailio (LAN uniquement)

**Fichiers :**
- Créer : `sip-stack/roomkit-visio/.env` (jamais commité — même motif que `.env` racine)
- Vérifier : `sip-stack/roomkit-visio/docker/postgres/initdb/02_insert_data_dev.sh` (déjà
  correct tel quel amont — `uacreg` désactivé par défaut, rien à changer)

- [ ] **Étape 1 : générer `.env` avec l'IP LAN réelle du HP**

```bash
cd ~/workplace/sip-stack/roomkit-visio
IP_HP=$(hostname -I | awk '{print $1}')   # attendu : 192.168.1.89
sed "s/^MY_IP_ADDR=.*/MY_IP_ADDR=${IP_HP}/" .env.example > .env
grep -E '^LIVEKIT_API_(KEY|SECRET)=' ../../oria-stack/oria/.env >> .env
cat .env   # vérifier : MY_IP_ADDR=192.168.1.89 + les deux clés LiveKit
```

- [ ] **Étape 2 : générer les certs TLS auto-signés (pas de dépôt `meet`, donc pas de source à
  copier — le Makefile amont bascule automatiquement sur l'auto-signature)**

```bash
cd ~/workplace/sip-stack/roomkit-visio
make certs
ls -la certs/   # attendu : tls.crt + tls.key
```

- [ ] **Étape 3 : vérifier que `02_insert_data_dev.sh` reste bien désactivé pour OVH (lecture
  seule, aucune modif attendue — juste confirmer avant de démarrer)**

```bash
grep -A3 "OVH SIP trunk row" ~/workplace/sip-stack/roomkit-visio/docker/postgres/initdb/02_insert_data_dev.sh
```
Attendu : `auth_password` reste une chaîne vide dans le script — **ne rien changer ici tant
que l'utilisateur n'a pas explicitement décidé de passer en Phase 2**.

- [ ] **Étape 4 : pas de commit** — `.env` est un secret local (clé LiveKit dedans), et `certs/`
  est déjà gitignoré par le dépôt amont (`.gitignore` de `roomkit-visio` l'exclut). Vérifier :

```bash
cd ~/workplace/sip-stack/roomkit-visio && git status --ignored | grep -E '\.env$|certs/'
```
Attendu : les deux apparaissent sous « Ignored files ».

---

### Tâche 4 — Build de `livekit-sip:local` depuis le fork `sip-video`

**Fichiers :** aucun fichier Workplace créé — build d'image Docker uniquement.

- [ ] **Étape 1 : cloner le fork (branche `sip-video`, jamais commité — cf. Tâche 1 Étape 2)**

```bash
cd ~/workplace/sip-stack
git clone -b sip-video https://github.com/suitenumerique/livekit-sip.git livekit-sip
```

- [ ] **Étape 2 : builder l'image locale**

```bash
cd ~/workplace/sip-stack/roomkit-visio
LIVEKIT_SIP_SRC=../livekit-sip make sip-build
```
Attendu : `docker build -f ../livekit-sip/build/sip/Dockerfile -t livekit-sip:local ../livekit-sip`
se termine sans erreur. **Si `go mod download` échoue** (dépendances réseau), le documenter tel
quel dans une note de suivi — c'est un point d'échec plausible sur un HP avec accès réseau
restreint, pas un bug de ce plan.

- [ ] **Étape 3 : vérifier l'image produite**

```bash
docker images livekit-sip:local
```
Attendu : une ligne avec une taille non nulle (le binaire Go + runtime GStreamer).

---

### Tâche 5 — Démarrer le stack, vérifier l'état (dispatcher, rtpengine, santé Kamailio)

**Fichiers :** aucun.

- [ ] **Étape 1 : démarrer (compose.yml + compose.override.yml de la Tâche 2)**

```bash
cd ~/workplace/sip-stack/roomkit-visio
docker compose -f compose.yml -f compose.override.yml up -d
docker compose -f compose.yml -f compose.override.yml ps
```
Attendu : `postgres-kamailio`, `kamailio`, `rtpengine`, `livekit-sip` tous `Up`/`healthy`
(kamailio dépend de `postgres-kamailio: service_healthy` — laisser le temps à l'initdb).

- [ ] **Étape 2 : si Kamailio a démarré avant la fin de l'initdb Postgres (piège connu amont,
  `docs/troubleshooting.md`), redémarrer une fois**

```bash
docker compose -f compose.yml -f compose.override.yml logs postgres-kamailio | grep "ready to accept connections"
docker compose -f compose.yml -f compose.override.yml restart kamailio
```

- [ ] **Étape 3 : vérifier la table dispatcher (doit pointer vers `livekit-sip:5080`)**

```bash
./bin/psql-kamailio.sh -c "SELECT destination FROM dispatcher;"
```
Attendu : une ligne `sip:192.168.1.89:5080;transport=tcp`.

- [ ] **Étape 4 : vérifier que Kamailio voit rtpengine**

```bash
docker compose -f compose.yml -f compose.override.yml exec kamailio kamcmd rtpengine.show all
```
Attendu : un seul rtpengine listé, non « disabled ».

- [ ] **Étape 5 : vérifier que `livekit-sip` a bien rejoint Redis et LiveKit d'Oria (pas d'erreur
  de connexion dans ses logs)**

```bash
docker compose -f compose.yml -f compose.override.yml logs livekit-sip | tail -50
```
Attendu : aucune ligne `connection refused` / `dial tcp` vers `redis:6379` ou `livekit:7880`.
**Si erreur ici** : vérifier que `livekit-sip` a bien rejoint `oria_net` (Tâche 2 Étape 2) —
`docker inspect roomkit-visio-livekit-sip-1 --format '{{json .NetworkSettings.Networks}}'`
doit lister le réseau Oria confirmé en Tâche 2 Étape 1.

---

### Tâche 6 — Créer la règle de dispatch SIP LiveKit (trou du README amont, risque n°5)

**Fichiers :** aucun fichier Workplace — appel API/CLI LiveKit uniquement.

**Interfaces :**
- Consomme : `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` d'Oria (mêmes valeurs que
  Tâche 3 Étape 1).
- Produit : un SIP Trunk entrant + une Dispatch Rule côté serveur LiveKit, mappant un numéro de
  test vers une room Oria — condition sine qua non pour qu'un appel SIP rejoigne une room
  (confirmé dans le code du fork, cf. risque n°5).

- [ ] **Étape 1 : installer le CLI `lk` sur le HP (si absent)**

```bash
curl -sSL https://get.livekit.io/cli | bash
lk --version
```

- [ ] **Étape 2 : créer un trunk SIP entrant LiveKit (pas OVH — un trunk *logique* côté LiveKit,
  qui décrit d'où `livekit-sip` a le droit d'accepter des appels)**

```bash
cat > /tmp/inbound-trunk.json <<'JSON'
{
  "trunk": {
    "name": "roomkit-visio-dev",
    "numbers": ["555"]
  }
}
JSON
lk sip inbound create --url ws://192.168.1.89:7880 \
  --api-key "$ORIA_LIVEKIT_API_KEY" --api-secret "$ORIA_LIVEKIT_API_SECRET" \
  /tmp/inbound-trunk.json
```
**Note honnête** : les noms de champs exacts (`trunk.numbers` etc.) sont ceux du LiveKit SIP
standard amont — le fork `sip-video` peut avoir étendu ce schéma (champs vidéo). **Vérifier
`lk sip inbound create --help` et, si besoin, `pkg/service/psrpc.go` du fork pour les champs
attendus avant d'exécuter**, plutôt que de supposer que ce JSON est final.

- [ ] **Étape 3 : créer la dispatch rule → room Oria de test**

```bash
cat > /tmp/dispatch-rule.json <<'JSON'
{
  "rule": {
    "dispatchRuleDirect": { "roomName": "sip-test-s197" }
  },
  "trunkIds": ["<ID retourné à l'Étape 2>"]
}
JSON
lk sip dispatch create --url ws://192.168.1.89:7880 \
  --api-key "$ORIA_LIVEKIT_API_KEY" --api-secret "$ORIA_LIVEKIT_API_SECRET" \
  /tmp/dispatch-rule.json
```

- [ ] **Étape 4 : vérifier que la room `sip-test-s197` peut être rejointe côté Oria (créer un
  world/room de test dans l'UI Oria, ou via `oria_worlds_lister`/le backend Oria directement) —
  pas de nouvelle capacité Cœur à créer ici, juste une room de test existante à disposition
  avant l'appel softphone de la Tâche 7.**

---

### Tâche 7 — Softphone LAN (Linphone/Zoiper) → appel de test → preuve bout-en-bout

**Fichiers :** aucun.

- [ ] **Étape 1 : installer un softphone SIP sur un appareil du LAN** (Linphone desktop/mobile,
  ou Zoiper) — pas sur le HP lui-même, un autre appareil du même réseau 192.168.1.0/24.

- [ ] **Étape 2 : configurer un compte SIP dans le softphone**

```
Serveur SIP  : 192.168.1.89:5060
Utilisateur  : (voir table subscriber — vide par défaut amont, à créer si Kamailio exige
                une auth ; sinon laisser anonyme si `ENABLE_IP_WHITELIST` couvre déjà le LAN)
Transport    : UDP
```
Si Kamailio refuse l'enregistrement anonyme, ajouter un subscriber de test :
```bash
cd ~/workplace/sip-stack/roomkit-visio
./bin/psql-kamailio.sh -c "INSERT INTO subscriber (username, domain, password) VALUES ('testphone', '192.168.1.89', 'test1234');"
make reload
```

- [ ] **Étape 3 : appeler le numéro de test configuré en Tâche 6 (`555`)**

- [ ] **Étape 4 : vérifier côté Oria que la room `sip-test-s197` a bien un participant SIP
  connecté avec de l'audio actif** (UI Oria, ou `docker compose logs livekit-sip` qui doit
  montrer `joinRoom` réussi avec `roomName: sip-test-s197` — cf. les logs vus au risque n°5,
  `pkg/sip/inbound.go` ligne ~1126).

- [ ] **Étape 5 : si l'audio est absent dans un seul sens (« one-way audio », piège connu
  amont)**, vérifier `MY_IP_ADDR` (`make show`) et l'annonce rtpengine :

```bash
docker compose -f compose.yml -f compose.override.yml exec rtpengine rtpengine-ctl ng list
```

- [ ] **Étape 6 : consigner le résultat (succès/échec, captures de logs) dans une note de suivi
  — pas de code, juste la preuve écrite que l'intégration technique fonctionne ou pas.** C'est
  le livrable qui permet à l'utilisateur de trancher la décision produit du risque n°8.

---

## Phase 2 — Production (hors scope de ce plan, listé mais PAS détaillé en tâches)

Ne sera abordé qu'une fois : (a) la Phase 1 a prouvé l'intégration technique, ET (b)
l'utilisateur a tranché le risque n°1 (souscription OVH réelle). Liste, non détaillée :

- Souscription effective du Trunk SIP OVH (formule + nombre de canaux + numéro géographique —
  devis à jour à demander, prix de ce plan non contractuels).
- Remplissage réel de la table `uacreg` avec les identifiants du trunk OVH (username, password,
  domaine `siptrunk.ovh.net` ou équivalent fourni par OVH à la souscription).
- Whitelist stricte des IP du trunk OVH dans la table `address` (jamais `0.0.0.0/0`).
- Ouverture effective des ports SIP/RTP vers Internet (pare-feu du HP + routeur/box + éventuel
  NAT) — décision de sécurité utilisateur, cf. risque n°2.
- Durcissement sécurité : fail2ban ou équivalent sur les tentatives SIP, rate limiting Kamailio,
  TLS/SRTP forcés côté trunk si supporté par OVH.
- Activation continue du stack de monitoring (`make start-all` — Prometheus/Grafana/Loki) pour
  surveiller qualité d'appel et fraude toll.
- Décision produit définitive : ce pont remplace-t-il la voix Twilio de `briques/telephonie`,
  ou vient-il en plus (SMS reste Twilio, voix bascule sur ce pont) ? Si « en plus » ou
  « remplace », prévoir alors — **et seulement alors** — une fine brique Cœur
  (`briques/telephonie-sip/manifest.json`, capacités de lecture d'état type
  `telephonie_sip_config`/`telephonie_sip_appels_lister`) pour rendre le pont pilotable par
  l'assistant, sur le modèle de `briques/oria/` (proxy léger devant un stack externe déjà
  vendoré). Non fait ici — YAGNI tant que la Phase 1 n'a pas prouvé la valeur.
- ADR à rédiger dans `docs/decisions/` une fois la décision produit prise (convention du projet,
  cf. mémoire `feedback-registre-decisions`).

---

## Self-Review

- **Couverture** : contexte SIP/PSTN/OVH (risques 1-2), choix d'hôte (risque 3, contrainte
  globale), build livekit-sip (risque 4, Tâche 4), dispatch rule (risque 5, Tâche 6), réseau
  redis/LiveKit (risque 6, Tâches 2-3), licences (risque 7), non-décision produit (risque 8) —
  chacun a soit une tâche Phase 1 dédiée, soit une note explicite « appartient à l'utilisateur ».
- **Pas de placeholder** : chaque étape a une commande ou un contenu de fichier réel — pas de
  "TODO"/"à définir" sauf les deux endroits explicitement marqués comme incertains et à vérifier
  empiriquement au moment de l'exécution (nom du réseau Docker Oria, schéma exact `lk sip
  inbound create` du fork) — ce sont des inconnues réelles de recherche, pas des trous de plan.
- **Cohérence** : `ORIA_LIVEKIT_API_KEY`/`ORIA_LIVEKIT_API_SECRET` utilisés de façon identique
  entre Tâche 2 (écriture YAML), Tâche 3 (écriture `.env`) et Tâche 6 (appel `lk`) ; le réseau
  `oria_net` de la Tâche 2 est le même nom réutilisé en Tâche 5 pour le diagnostic.
- **Aucun commit de secret** : `.env` et `certs/` explicitement exclus du commit en Tâche 3.
