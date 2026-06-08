# Brancher la voix full-duplex Kyutai Unmute sur Workplace

> **Statut : préparé, NON lancé.** Unmute exige un **GPU NVIDIA** — impossible sur le Mac
> Intel de dev. Tout est prêt pour le jour où tu as la machine. Côté Workplace, le passage
> à Unmute est déjà une **simple config** (panneau ⚙ Cerveau → Voix → Unmute + URL).

## Ce qu'est Unmute (et pourquoi c'est la bonne archi)
Unmute = **STT + ton LLM + TTS** de Kyutai, en temps réel (WebSocket calqué sur l'API
Realtime d'OpenAI). Il **enrobe notre assistant par la Gateway** : on lui dit « ton LLM,
c'est `http://…:4001/v1` » et il parle/écoute autour. Voix naturelle, on peut couper la
parole. MIT.

⚠️ **Nuance honnête** : en mode Unmute, c'est Unmute qui pilote la conversation avec le LLM
— il **n'utilise pas** la boucle à outils de l'assistant Workplace (pas de `livrer`,
`classer_document`, mémoire…). C'est donc un **mode brainstorming/discussion à la voix**.
Pour piloter l'usine à la voix avec confirmation, garde le mode **Navigateur** (Web Speech),
qui passe par `/assistant/chat` et ses outils.

## 👉 Le jour du lancement
Suis le runbook pas-à-pas : **[GUIDE-LANCEMENT-GPU.md](GUIDE-LANCEMENT-GPU.md)** (pré-vol GPU,
réseau vers la Gateway, lancement, et surtout la **validation/ajustement de l'audio Opus**
dans les DevTools — la seule partie non testée sans GPU).

## Pré-requis matériels (à vérifier AVANT)
- **GPU NVIDIA, VRAM ≥ 16 Go** (STT ~2,5 Go + TTS ~5,3 Go + marge). Le LLM, lui, tourne
  sur la Gateway de Workplace (pas sur ce GPU).
- **Linux x86_64** (ou Windows + WSL2). **Pas de macOS / Apple Silicon.**
- Docker + `nvidia-container-toolkit` (accès GPU dans les conteneurs).
- Un token Hugging Face (poids Kyutai au 1er démarrage).

## Mise en route (sur la machine GPU)
```bash
# 1) Cloner Unmute DANS ce dossier (à côté des fichiers Workplace fournis ici)
git clone https://github.com/kyutai-labs/unmute .

# 2) Configurer le lien vers la Gateway de Workplace
cp .env.example .env
#   → édite .env : KYUTAI_LLM_URL (host.docker.internal si même machine, sinon l'IP de
#     la machine Workplace), KYUTAI_LLM_API_KEY (= LITELLM_MASTER_KEY), KYUTAI_LLM_MODEL,
#     HUGGING_FACE_HUB_TOKEN.

# 3) Lancer Unmute en pointant sur la Gateway (override Workplace par-dessus)
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
```
L'override (`docker-compose.override.yml`, fourni ici) :
- réécrit l'environnement du service **backend** → `KYUTAI_LLM_URL` / `KYUTAI_LLM_API_KEY` /
  `KYUTAI_LLM_MODEL` vers **notre Gateway** ;
- met le service **llm** (vLLM embarqué) à **0 réplique** → tout le GPU pour STT+TTS.

> La Gateway de Workplace doit être joignable depuis la machine GPU. Si GPU distant :
> ouvre le port **4001** de la machine Workplace (ou tunnel SSH). Pense aussi à exposer
> un modèle adapté dans `briques/gateway/litellm_config.yaml`.

## Brancher côté Workplace (déjà prêt)
1. Dashboard → onglet **Assistant** → **⚙ Cerveau** → section **Voix temps réel**.
2. Choisis **« Kyutai Unmute »**, saisis l'URL WebSocket du backend Unmute, p. ex.
   `wss://mon-serveur:8000/v1/realtime` (ou via Traefik en HTTPS) → **Enregistrer la voix**.
3. Le réglage est **persisté** (`/data/assistant_config.json`) et le front reconstruit le
   fournisseur voix : le bouton 🎤 ouvre alors une **conversation full-duplex** avec Unmute.

Pour revenir au mode local : rechoisis **« Navigateur »** → Enregistrer.

## Détails techniques (déjà câblés dans le front)
- Client : `creerUnmute(url)` dans le dashboard (WS sous-protocole `realtime`).
- Handshake : `session.update` (instructions FR + voix) avant tout.
- Micro → `input_audio_buffer.append` ; réponses `response.text.delta` (affiché) +
  `response.audio.delta` (joué). Audio **Opus 24 kHz mono base64** via **WebCodecs**.
- À valider avec un vrai serveur : le détail des champs `session.update`/voix et le format
  Opus exact peuvent différer selon la version d'Unmute (cf. `unmute/openai_realtime_api_events.py`
  et `docs/browser_backend_communication.md`). Aucun impact sur le mode Navigateur.
