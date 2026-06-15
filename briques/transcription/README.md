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
   *best-effort* si installée + `HF_TOKEN`, sinon `diarisation: false` (honnête).
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
- *(à venir, incrément séparé)* `gdrive` via l'API Google Drive (OAuth, pont Google S27/S35).

```bash
# archiver des notes existantes dans la mémoire (souverain)
curl -X POST localhost:5980/archiver -H 'Content-Type: application/json' \
  -d '{"notes":{"resume":"...","decisions":["..."]},"titre":"Réunion","destination":"memoire"}'

# tout en un : audio → transcription + notes + dépôt dans un dossier synchronisé
curl -F fichier=@reunion.m4a -F destination=dossier localhost:5980/notes
```

Si la destination échoue (mémoire injoignable, dossier absent), la réponse porte
`{"ok": false, "erreur": "..."}` — **les notes ne sont jamais perdues en silence**.

## Lancer

```bash
docker compose up --build            # port 5980
curl localhost:5980/sante
curl -F fichier=@reunion.m4a localhost:5980/notes
```

## Tests

```bash
pytest -q                            # offline, déterministe (mode placeholder)
```
