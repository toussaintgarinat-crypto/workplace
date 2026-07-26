# standard-telephonique — standard vocal IVR + répondeur générique

Fondation téléphonique commune (S197+) : décroche les appels SIP entrants (via
`sip-stack/roomkit-visio/`), joue un menu à 7 options, enregistre un message vocal
(toutes les options tombent aujourd'hui sur le répondeur générique), le transcrit
(`briques/transcription`) et notifie Telegram (`briques/connexion`).

## Démarrer

Prérequis : `sip-stack/roomkit-visio/` déjà démarré (fournit le réseau Docker
`roomkit-visio_default` et le LiveKit dédié), `.env` racine avec
`STANDARD_TEL_LIVEKIT_API_KEY`/`_SECRET` (mêmes valeurs que
`sip-stack/roomkit-visio/.env`).

**Piège Compose** : `environment: - LIVEKIT_API_KEY=${STANDARD_TEL_LIVEKIT_API_KEY}`
n'est interpolé par Compose qu'à partir du `.env` de **son propre** répertoire de
projet — `env_file: ../../.env` ne suffit pas (ça injecte seulement dans le
conteneur, pas dans l'interpolation `${...}` du YAML lui-même). Avant de démarrer,
créer un lien vers le `.env` racine (jamais commité, comme `.env` lui-même) :

```bash
ln -sf ../../.env briques/standard-telephonique/.env
docker compose up -d --build
```

Deux services : `standard-telephonique-api` (port 6190, capacité assistant
`standard_telephonique_messages_lister`) et `standard-telephonique-agent` (worker
`livekit-agents`, rejoint automatiquement chaque appel — aucun port exposé).

## Limite connue (bloquant sur le HP actuellement)

Le worker `standard-telephonique-agent` **plante en boucle sur le HP** (SIGILL). Le CPU
virtuel de la VM Proxmox (QEMU, sans AVX2) est incompatible avec `livekit-local-inference`,
une dépendance native de `livekit-agents` (détection de fin de tour de parole) — l'agent
n'utilise pourtant que du DTMF brut + `rtc.AudioStream`, pas de détection de tour de parole,
donc cette dépendance native n'est même pas utile ici. `docker compose up -d --build` sur le
HP démarre le conteneur, qui crash-loop ensuite silencieusement (`restart: unless-stopped`,
aucun healthcheck sur ce service — rien ne signale le problème dans `docker compose ps`).

**Contournement utilisé pour prouver le code (3 vrais appels SIP via Linphone, bout en
bout : menu → délai → répondeur → raccroché → transcription → notification Telegram)** :
exécuter `agent.py` directement (hors Docker) sur une machine avec AVX2 (ex. un Mac de dev),
en pointant les variables d'environnement vers l'IP LAN réelle du HP plutôt que les noms de
service Docker internes :
```bash
LIVEKIT_URL=ws://<IP_LAN_HP>:7890 \
LIVEKIT_API_KEY=<meme valeur que sip-stack/roomkit-visio/.env> \
LIVEKIT_API_SECRET=<idem> \
VOIX_URL=http://<IP_LAN_HP>:5985 \
TRANSCRIPTION_URL=http://<IP_LAN_HP>:5980 \
CONNEXION_URL=http://<IP_LAN_HP>:5870 \
MESSAGES_DB=/chemin/local/messages.db \
MESSAGES_DIR=/chemin/local/audio \
python agent.py start
```
Solution temporaire, pas une correction définitive. Pistes pour un vrai déploiement sur le
HP : changer le type de CPU de la VM Proxmox (passthrough `host` ou modèle exposant AVX2),
ou héberger ce worker sur une machine dédiée à part.

**`sip-stack/roomkit-visio/`** (Kamailio + rtpengine + livekit-sip + LiveKit dont dépend cette
brique) est désormais versionné dans ce dépôt (`sip-stack/roomkit-visio/`, secrets exclus)
— voir [`sip-stack/README.md`](../../sip-stack/README.md) pour la procédure complète de
reconstruction sur une VM neuve (clone épinglé de `livekit-sip`, bootstrap, `.env`). Les
deux fichiers `.env` (`sip-stack/roomkit-visio/.env` et le `.env` racine de ce monorepo)
doivent toujours porter la même valeur de clé/secret LiveKit (`LIVEKIT_API_KEY`/`_SECRET`
côté sip-stack, `STANDARD_TEL_LIVEKIT_API_KEY`/`_SECRET` côté racine) — rien ne garantit
aujourd'hui qu'ils restent synchronisés au-delà de la vigilance manuelle.

## Hors périmètre (voir docs/superpowers/specs/2026-07-25-standard-vocal-ivr-repondeur-design.md)

Les 7 usages réels (rendez-vous, écoute réunion, etc.), le vrai numéro de téléphone
(OVH/Twilio), le branchement sur le LiveKit réel d'Oria.
