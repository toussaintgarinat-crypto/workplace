# Brique `voix` — synthèse vocale (TTS) souveraine

Texte → audio en API. **Miroir exact de la brique `transcription`** (audio → texte), dans
l'autre sens. Souveraine par défaut (Piper local, CPU), provider-agnostique, repli honnête.

## API

| Méthode | Chemin          | Rôle |
|---------|-----------------|------|
| `GET`   | `/sante`        | fournisseurs connus / configurés, moteur actif, souveraineté |
| `GET`   | `/voix`         | catalogue des moteurs TTS + lesquels sont configurés |
| `POST`  | `/synthetiser`  | `{texte, voix?, langue?, format?, fournisseur?}` → **octets audio** (ou JSON `place_holder` honnête) |

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

## Synergie

Le pont `connexion` appelle cette brique pour **répondre en vocal** quand l'interlocuteur a
parlé (message vocal Telegram) → boucle *speech-to-speech* (transcription ← S72, voix → S73).
