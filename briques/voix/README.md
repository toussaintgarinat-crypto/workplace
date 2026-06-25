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
| `GET`   | `/`             | **page de réglage** : choisir le moteur de voix en un clic + bouton « Tester » |
| `GET`   | `/sante`        | fournisseurs TTS connus / configurés, moteur actif, souveraineté, `temps_reel` |
| `GET`   | `/voix`         | catalogue des moteurs TTS + lesquels sont configurés |
| `GET`   | `/voix/moteur`  | état pour la page : moteurs `choisi` (conversation) + `lecture`, `seuil`, `actif`, liste |
| `POST`  | `/voix/moteur`  | `{fournisseur, role}` → **bascule en un clic** d'un rôle (`conversation`/`lecture` ; `auto`=défaut) |
| `POST`  | `/synthetiser`  | `{texte, voix?, langue?, format?, fournisseur?, usage?}` → **octets audio** (ou JSON `place_holder` honnête) |
| `GET`   | `/voix/realtime`| catalogue des fournisseurs de chat vocal temps réel + leur état |
| `WS`    | `/realtime/openai` | relais WebSocket ↔ OpenAI Realtime (PCM16 24 kHz) |
| `WS`    | `/realtime/google` | relais WebSocket ↔ Gemini Multimodal Live |
| `WS`    | `/realtime/grok`   | relais WebSocket ↔ xAI Grok Realtime (OpenAI-compatible) |

La réponse de `/synthetiser` est **binaire** (Content-Type `audio/ogg`, `audio/mpeg`…)
quand un moteur a répondu, avec les en-têtes `X-Backend` et `X-Format`. Si aucun moteur
n'est disponible, la réponse est un JSON `{"place_holder": true, "note": …}` — **jamais de
fausse voix**.

### Voix par USAGE (conversation rapide / lecture belle)

Une voix unique n'est pas idéale : une **conversation** veut de la rapidité, un **résumé** (ou
tout long texte qu'on écoute posément) veut une belle voix, la latence n'y gêne pas. La brique
gère donc **deux rôles** (persistés, réglables en un clic depuis `GET /`) :

- `moteur` (clé) = voix de **conversation** (réponses courtes) ;
- `moteur_lecture` (clé) = voix de **lecture** (résumés, narration).

`POST /synthetiser` route tout seul : si `usage` est forcé (`conversation`/`lecture`) il décide ;
sinon il compare la longueur du texte (après nettoyage) au seuil `VOIX_SEUIL_LECTURE` (défaut
**280** car.) — au-delà, c'est la voix de lecture. La voix de lecture n'est préposée que si elle
est **choisie et disponible** ; sinon repli honnête sur la voix de conversation. Tout consommateur
(dont le speech-to-speech Telegram) en bénéficie : un résumé long part automatiquement dans la
belle voix, une réponse courte dans la voix rapide. *(Choix du moteur de lecture — Coqui local ou
hébergé — et clonage de voix réutilisables : sprints dédiés à venir.)*

### Lecture propre (nettoyage avant TTS)

Avant d'envoyer le texte au moteur, `nettoyer.pour_la_voix()` (appelé en UN point :
`moteur.synthetiser`) le rend **parlable** : retrait du markdown (`**`, titres `#`, listes),
des emoji, des liens (garde le libellé, jette l'URL), des blocs de code, des horodatages de
chapitres ; les puces/titres deviennent des phrases. La **ponctuation est conservée** (`. ,`
font les pauses — Piper ne les épelle pas). Un texte qui n'a plus rien à dire (que des emoji)
→ placeholder honnête. Tout consommateur de `/synthetiser` en bénéficie (dont le
speech-to-speech Telegram).

## Fournisseurs (ordre par défaut, surchargé par `VOIX_PROVIDERS`)

1. `piper` — **souverain**, local (CPU). Demande le binaire `piper` (fourni par `piper-tts`)
   **et** un modèle de voix `.onnx` désigné par `PIPER_VOICE`. Le texte ne quitte pas la machine.
2. `kokoro` — **local naturel, OPT-IN inerte** (`VOIX_KOKORO=1` + lib installée). Voir plus bas.
3. `coqui` — **local naturel, OPT-IN inerte** (`VOIX_COQUI=1` + lib installée). Voir plus bas.
4. `openai` — `OPENAI_API_KEY` (`/v1/audio/speech`, format `opus` par défaut, `OPENAI_TTS_VOICE`).
5. `elevenlabs` — `ELEVENLABS_API_KEY` (`ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`).
6. `gateway` — `GATEWAY_KEY` (proxy OpenAI-compatible ; honnête : échoue proprement si la
   Gateway ne route pas le TTS, on retombe sur le suivant).

## Moteur souverain (Piper)

Télécharger une voix une fois (ex. voix française), la poser dans `./voix-modeles`, puis :

```bash
PIPER_VOICE=/voix-modeles/fr_FR-voice.onnx
```

Modèles : https://github.com/rhasspy/piper (fichiers `.onnx` + `.onnx.json`).

## Voix NATURELLE locale (kokoro / coqui) — OPT-IN inerte

Piper est rapide et souverain mais sonne « synthétique ». Deux moteurs **locaux** rendent
une voix bien plus **naturelle**, au prix d'une exécution **lourde** (gros modèles, GPU
conseillé). Ils sont **inertes par défaut** : la dépendance n'est pas dans `requirements.txt`
(importée paresseusement → l'image ne change pas) et `disponible()` exige un drapeau d'env.
Tant qu'on ne les active pas, la brique reste sur Piper, sans aucun changement.

| Moteur | Forces | Activation |
|---|---|---|
| `kokoro` | ~82M params, Apache, très naturel pour sa taille (FR : `ff_siwis`) | `pip install kokoro soundfile` + `VOIX_KOKORO=1` |
| `coqui` (XTTS-v2) | multilingue + **clonage de voix** (échantillon WAV) | `pip install coqui-tts` + `VOIX_COQUI=1` + `COQUI_SPEAKER_WAV=/ref.wav` |

**Activation de Kokoro (déjà câblée dans le compose, `build.args.INSTALL_KOKORO=1`) :**
l'image installe `kokoro soundfile misaki[fr]` (+ `espeak-ng`, torch CPU-only) et le runtime
pose `VOIX_KOKORO=1`. La voix est ensuite **sélectionnable en un clic** depuis `GET /`
(http://localhost:5985/) ou via `POST /voix/moteur {"fournisseur":"kokoro"}`. Piper reste le
**défaut** (souverain) ; le choix de l'utilisateur est persisté dans `VOIX_DIR` (`/data/voix`).
Pour une image légère sans voix naturelle : `INSTALL_KOKORO=0` + `VOIX_KOKORO=0`.

**Coqui/XTTS (le jour où la machine a un GPU) :**

1. installer la dépendance (cf. `requirements-voix-naturelle.txt`) dans l'image ;
2. poser le drapeau au **`.env` racine** (pas dans le compose — piège env-shadow) :
   `VOIX_COQUI=1` (`COQUI_SPEAKER_WAV`, `COQUI_LANG=fr`, `COQUI_DEVICE=cuda` si GPU) ;
3. sélectionner « Coqui » dans la page de réglage (ou `VOIX_PROVIDERS=coqui,piper`).

Variables : `KOKORO_VOICE` (déf. `ff_siwis`), `KOKORO_LANG` (déf. `f`), `KOKORO_SPEED` ;
`COQUI_MODEL` (déf. XTTS-v2), `COQUI_SPEAKER_WAV` **ou** `COQUI_SPEAKER`, `COQUI_LANG`
(déf. `fr`), `COQUI_DEVICE`.

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
