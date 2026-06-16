# Brique `transcription` — audio→texte souverain

Transcription audio→texte **en API**, inspirée de Notta/Otter mais **sans aucun appel à un
tiers imposé** : on héberge notre propre moteur. Produit **autonome** (miroir des briques
`images`/`video`), composable par l'assistant et le Studio.

> **Souverain par défaut.** Contrairement à images/vidéo (qui ont besoin d'un GPU et passent
> par des fournisseurs hébergés), **Whisper tourne très bien sur CPU/Metal**. Le moteur
> `local` est donc **en tête** : l'audio ne quitte pas la machine. Les fournisseurs hébergés
> ne sont qu'un **repli OPT-IN** pour qui les configure.

## Endpoints

| Méthode | Route             | Rôle |
|---------|-------------------|------|
| `POST`  | `/transcrire`     | Upload d'un fichier audio → transcription (+ diarisation optionnelle) |
| `POST`  | `/transcrire-url` | URL d'un audio → transcription |
| `POST`  | `/resumer`        | Transcription (texte) → notes (résumé / points d'action / décisions) |
| `POST`  | `/notes`          | **Le flux complet** : upload audio → transcription **+** notes (+ archivage optionnel) |
| `POST`  | `/archiver`       | Dépose des notes dans une destination au choix (mémoire ou dossier) |
| `GET`   | `/destinations`   | Catalogue des destinations d'archivage + défaut |
| `GET`   | `/sante`          | Moteur actif, souveraineté, synthèse LLM dispo |
| `GET`   | `/fournisseurs`   | Catalogue des moteurs + lesquels sont configurés |

Réponse de `/transcrire` (forme normalisée) :

```json
{
  "texte": "...",
  "segments": [{"debut": 0.0, "fin": 3.2, "texte": "...", "locuteur": "A"}],
  "langue": "fr",
  "diarisation": true,
  "backend": "local",
  "place_holder": false
}
```

**Repli honnête** : sans moteur configuré, `place_holder: true` et `texte: ""` — jamais de
fausse transcription, jamais de texte inventé.

## Fournisseurs (ordre par défaut)

1. **`local`** — Whisper (faster-whisper, CPU/Metal). **Souverain.** Diarisation pyannote
   *best-effort* (voir ci-dessous), sinon `diarisation: false` (honnête).
2. `openai` — `/audio/transcriptions` (whisper-1 / gpt-4o-transcribe). Pas de diarisation.
3. `deepgram` — `/v1/listen?diarize=true` : segments **avec** locuteurs.
4. `assemblyai` — `speaker_labels=true` : segments **avec** locuteurs.
5. `gateway` — Gateway Workplace (proxy OpenAI-compatible), zéro clé propre.

Ordre surchargé par `TRANSCRIPTION_PROVIDERS` (ex. `local` = 100 % souverain). Toute clé
absente → fournisseur ignoré.

## Synthèse des notes (≈0 $)

`/resumer` et `/notes` synthétisent via l'**économe gratuit** par la Gateway (motif briefing
S30). Sans `GATEWAY_KEY` : repli **heuristique honnête** (premières phrases, `source:
heuristique`). Langue de sortie paramétrable (FR/EN/ES/AR/PT/DE/IT) — on peut transcrire
dans une langue et résumer dans une autre.

## Archiver les notes (pont consenti, opt-in)

Les notes peuvent être **déposées dans une destination au choix** — jamais automatiquement
(esprit « pont consenti » du CRM S24). Destination explicite par appel, défaut **souverain** :

- **`memoire`** (défaut) — la brique mémoire Workplace (5600), souveraine. Le résumé part en
  Markdown via `/retenir`, points d'action / thèmes / décisions en `metadata`.
- **`dossier`** — écrit un `.md` dans un dossier au choix (`dossier=...` ou `NOTES_DOSSIER`).
  Pointe ce dossier vers un dossier **synchronisé par ton drive** (Google Drive / iCloud /
  Dropbox, app de bureau) → la note remonte sur le drive **sans OAuth ni API tierce**.
- **`gdrive`** — l'**API Google Drive** directement (OAuth, refresh token). Configure
  `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN` (consentement une fois,
  scope `drive.file`) et éventuellement `GDRIVE_FOLDER_ID` (dossier cible, ou param `dossier`).
  La note `.md` est uploadée via `multipart/related`. Opt-in.

```bash
# archiver des notes existantes dans la mémoire (souverain)
curl -X POST localhost:5980/archiver -H 'Content-Type: application/json' \
  -d '{"notes":{"resume":"...","decisions":["..."]},"titre":"Réunion","destination":"memoire"}'

# tout en un : audio → transcription + notes + dépôt dans un dossier synchronisé
curl -F fichier=@reunion.m4a -F destination=dossier localhost:5980/notes
```

Si la destination échoue (mémoire injoignable, dossier absent), la réponse porte
`{"ok": false, "erreur": "..."}` — **les notes ne sont jamais perdues en silence**.

## Diarisation souveraine (« qui parle ») — optionnelle

En local, l'identification des intervenants est **best-effort** via **pyannote** (souverain,
aucun envoi). Pour l'activer :

```bash
pip install -r requirements-diarisation.txt           # pyannote.audio + torch (lourd)
# accepter les conditions du modèle pyannote sur huggingface.co, créer un token, puis :
DIARISATION_LOCAL=1 HF_TOKEN=<token> docker compose up
```

Sans ces conditions (ou avec un fournisseur cloud qui ne diarise pas), la réponse porte
`diarisation: false` — jamais de locuteurs inventés. Deepgram / AssemblyAI diarisent nativement.

## Front (capter un appel, façon Granola — sans bot)

La brique sert un front en une page à **`/`** et **`/atelier`** (vanilla, thème dark+or,
embarquable en iframe comme Studio/Personnages). Trois entrées :

- **🖥️ Capter l'appel** — le navigateur demande de *partager* l'onglet/la fenêtre de la
  réunion (Zoom/Meet/Teams web) ; coche « partager l'audio ». On **mixe cet audio (les
  autres) avec ton micro (toi)** via Web Audio, on enregistre, on envoie à `/notes`. Aucun
  bot ne rejoint l'appel — comme Granola. 100 % local côté capture.
- **🎤 Mémo** — enregistre le micro seul (note vocale, réunion en présentiel sur haut-parleur).
- **📁 Importer** — un fichier audio/vidéo existant.

Puis : transcription + notes affichées, et bouton **Ranger** vers mémoire ou dossier/drive.

> Pour capter *tout* le son système (toutes apps, pas juste un onglet du navigateur — ex.
> client Zoom natif), utilise le **capteur natif macOS** : `capteur-macos/` (ScreenCaptureKit,
> sans pilote ni bot, façon Granola). Voir son README.

## Assistant (le Jarvis pilote)

Outils `transcription_*` côté noyau (`core/outils.py`) : `transcription_etat`,
`transcription_depuis_url` (URL audio → transcription + notes), `transcription_resumer`
(texte → notes), `transcription_destinations`, `transcription_archiver` (range les notes,
action gardée par `confirme`). Auth de service optionnelle via `TRANSCRIPTION_KEY` (motif
`STUDIO_KEY`). L'upload de fichier / la capture d'appel se font dans le front.

## Lancer

```bash
docker compose up --build            # port 5980, front sur http://localhost:5980/atelier
curl localhost:5980/sante
curl -F fichier=@reunion.m4a localhost:5980/notes
```

## Tests

```bash
pytest -q                            # offline, déterministe (mode placeholder)
```
