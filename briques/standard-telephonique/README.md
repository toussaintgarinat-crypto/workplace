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

## Hors périmètre (voir docs/superpowers/specs/2026-07-25-standard-vocal-ivr-repondeur-design.md)

Les 7 usages réels (rendez-vous, écoute réunion, etc.), le vrai numéro de téléphone
(OVH/Twilio), le branchement sur le LiveKit réel d'Oria.
