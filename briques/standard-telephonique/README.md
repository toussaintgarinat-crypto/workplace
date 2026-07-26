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

## Déploiement (VM dédiée, résolu 2026-07-26)

Le worker `standard-telephonique-agent` **plantait en boucle** (SIGILL) quand `sip-stack/`
tournait sur la VM Proxmox `103` (192.168.1.89, celle qui héberge le reste du stack
Workplace) : son CPU virtuel générique (`x86-64-v2-AES`) est incompatible avec
`livekit-local-inference`, une dépendance native de `livekit-agents`. Root cause confirmée
via `lscpu` : `x86-64-v2` ne garantit pas AVX2 même quand le CPU physique l'a (i7-8700, qui
l'a bien).

**Solution retenue** : `sip-stack/` (Kamailio + rtpengine + livekit-sip + LiveKit) et cette
brique tournent maintenant sur une **VM Proxmox dédiée** (`sip-stack-vm`, VMID 104,
`192.168.1.188`, clonée d'un template Debian 13, `cpu: host` — expose AVX2 du CPU physique
au guest, vérifié via `lscpu | grep avx2`), séparée de la VM 103 pour aussi isoler ce
service exposé au réseau (SIP = cible classique de brute-force/toll fraud) du reste du
stack. Réseau LAN/mesh uniquement, pas d'exposition WAN (le vrai trunk OVH reste hors
périmètre, voir plus bas). `standard-telephonique-api` (port 6190, capacité assistant)
reste sur la VM 103 — elle ne touche pas au SIP, pas de raison de la déplacer.

Procédure de reconstruction complète : [`sip-stack/README.md`](../../sip-stack/README.md).
Les deux fichiers `.env` (`sip-stack/roomkit-visio/.env` sur la VM 104 et le `.env` racine
de ce monorepo, sur les DEUX VMs) doivent porter la même valeur de clé/secret LiveKit
(`LIVEKIT_API_KEY`/`_SECRET` côté sip-stack, `STANDARD_TEL_LIVEKIT_API_KEY`/`_SECRET` côté
racine) — rien ne garantit aujourd'hui qu'ils restent synchronisés au-delà de la vigilance
manuelle. Sur la VM 104, le `.env` racine doit aussi pointer `VOIX_URL`/`TRANSCRIPTION_URL`/
`CONNEXION_URL` vers `http://192.168.1.89:<port>` (ces services restent sur la VM 103, le
défaut `host.docker.internal` ne suffit plus une fois les deux VMs séparées).

Pour tester avec un softphone (ex. Linphone), s'enregistrer sur `192.168.1.188:5060`
(remplace l'ancienne IP `192.168.1.89` utilisée avant cette migration).

Ancien contournement (agent exécuté hors Docker sur un Mac de dev, utilisé le temps de
prouver le code) **retiré** — plus nécessaire, l'agent tourne en conteneur normal sur la
VM 104 (`RestartCount: 0`, `registered worker` dans les logs, pas de crash-loop).

## Hors périmètre (voir docs/superpowers/specs/2026-07-25-standard-vocal-ivr-repondeur-design.md)

Les 7 usages réels (rendez-vous, écoute réunion, etc.), le vrai numéro de téléphone
(OVH/Twilio), le branchement sur le LiveKit réel d'Oria.
