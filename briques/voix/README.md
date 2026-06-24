# Brique `voix` — TTS souverain + chat vocal temps réel

Deux versants vocaux en API :

1. **TTS** texte → audio (one-shot). **Miroir exact de la brique `transcription`** (audio →
   texte), dans l'autre sens. Souverain par défaut (Piper local, CPU), provider-agnostique,
   repli honnête.
2. **Chat vocal TEMPS RÉEL** (speech-to-speech) — **porté du plugin `voice` de
   [Gungnir](https://github.com/kevinggraphiste-hub/Gungnir)**. La brique relaie un WebSocket
   navigateur ↔ l'API temps réel d'un fournisseur (vrai audio bidirectionnel, VAD côté
   fournisseur, pas de STT/TTS séparé). **OPT-IN, inerte sans clé.**

## API

| Méthode | Chemin          | Rôle |
|---------|-----------------|------|
| `GET`   | `/sante`        | fournisseurs TTS connus / configurés, moteur actif, souveraineté, `temps_reel` |
| `GET`   | `/voix`         | catalogue des moteurs TTS + lesquels sont configurés |
| `POST`  | `/synthetiser`  | `{texte, voix?, langue?, format?, fournisseur?}` → **octets audio** (ou JSON `place_holder` honnête) |
| `GET`   | `/voix/realtime`| catalogue des fournisseurs de chat vocal temps réel + leur état |
| `WS`    | `/realtime/openai` | relais WebSocket ↔ OpenAI Realtime (PCM16 24 kHz) |
| `WS`    | `/realtime/google` | relais WebSocket ↔ Gemini Multimodal Live |
| `WS`    | `/realtime/grok`   | relais WebSocket ↔ xAI Grok Realtime (OpenAI-compatible) |

La réponse de `/synthetiser` est **binaire** (Content-Type `audio/ogg`, `audio/mpeg`…)
quand un moteur a répondu, avec les en-têtes `X-Backend` et `X-Format`. Si aucun moteur
n'est disponible, la réponse est un JSON `{"place_holder": true, "note": …}` — **jamais de
fausse voix**.

## Fournisseurs (ordre par défaut, surchargé par `VOIX_PROVIDERS`)

1. `piper` — **souverain**, local (CPU). Demande le binaire `piper` (fourni par `piper-tts`)
   **et** un modèle de voix `.onnx` désigné par `PIPER_VOICE`. Le texte ne quitte pas la machine.
2. `openai` — `OPENAI_API_KEY` (`/v1/audio/speech`, format `opus` par défaut, `OPENAI_TTS_VOICE`).
3. `elevenlabs` — `ELEVENLABS_API_KEY` (`ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`).
4. `gateway` — `GATEWAY_KEY` (proxy OpenAI-compatible ; honnête : échoue proprement si la
   Gateway ne route pas le TTS, on retombe sur le suivant).

## Moteur souverain (Piper)

Télécharger une voix une fois (ex. voix française), la poser dans `./voix-modeles`, puis :

```bash
PIPER_VOICE=/voix-modeles/fr_FR-voice.onnx
```

Modèles : https://github.com/rhasspy/piper (fichiers `.onnx` + `.onnx.json`).

## Chat vocal temps réel (porté de Gungnir)

Conversation vocale bidirectionnelle. Le navigateur ouvre un WebSocket sur la brique, qui
le relaie vers l'API temps réel du fournisseur choisi. Chaque relais est **inerte tant que
sa clé n'est pas renseignée** (le cœur souverain Piper reste le défaut — rien ici ne le
remplace). Clés lues dans l'env (héritées du `.env` racine) :

| Fournisseur | Clé(s) acceptée(s) (alias dédié prioritaire) |
|---|---|
| `openai` (OpenAI Realtime) | `VOIX_OPENAI_API_KEY` › `OPENAI_API_KEY` |
| `google` (Gemini Live)     | `VOIX_GOOGLE_API_KEY` › `GEMINI_API_KEY` › `GOOGLE_API_KEY` |
| `grok` (xAI Grok Realtime) | `VOIX_XAI_API_KEY` › `XAI_API_KEY` › `GROK_API_KEY` |

`VOIX_AGENT_NOM` (défaut `Assistant`) nomme l'assistant dans la session. Auth du WebSocket :
jeton porté par le header `Authorization: Bearer …`, le sous-protocole `bearer.<jeton>` ou
`?token=` ; ouvert si `API_KEYS` est vide (comme le reste de la brique).

**Découplage vs Gungnir** : l'original lisait des clés par-utilisateur en base et
authentifiait contre une table `User`. Ici, conformément au modèle brique Workplace, les
clés viennent de l'env et l'auth WS se fait contre `API_KEYS`.

## Synergie

Le pont `connexion` appelle cette brique pour **répondre en vocal** quand l'interlocuteur a
parlé (message vocal Telegram) → boucle *speech-to-speech* (transcription ← S72, voix → S73).
Le chat temps réel offre, lui, une conversation vocale continue côté navigateur.
