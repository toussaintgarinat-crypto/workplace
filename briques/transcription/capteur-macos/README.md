# `capteur` — capture d'appel native macOS (façon Granola, sans bot ni pilote)

Petit exécutable Swift qui fait, **en local**, ce que le navigateur ne peut pas : capter la
**sortie audio système** (la voix des autres participants, depuis *n'importe quelle* app —
client Zoom natif, Meet, Teams, FaceTime…) **+ ton micro**, les mixer, et envoyer le tout à
la brique transcription (`POST /notes`). C'est le mécanisme de Granola : aucun robot ne
rejoint l'appel, rien ne sort de la machine côté capture.

- **Sortie système** via **ScreenCaptureKit** (`capturesAudio`) — aucun pilote tiers.
- **Micro** via la capture micro de ScreenCaptureKit (**macOS 15+**).
- `excludesCurrentProcessAudio` : on ne se capte pas soi-même.

## Construire

```bash
cd briques/transcription/capteur-macos
swift build -c release
# binaire : .build/release/capteur
```

## Autorisations (une seule fois)

macOS protège l'audio système et le micro. Au 1er lancement, accorde au terminal (ou au
binaire) :

- **Réglages → Confidentialité et sécurité → Enregistrement de l'écran** (pour l'audio système) ;
- **Réglages → Confidentialité et sécurité → Microphone**.

Sans ça, le capteur s'arrête avec un message clair (« l'utilisateur a refusé le protocole
TCC… ») — il ne capte jamais en douce.

## Utiliser

```bash
# enregistre jusqu'à Ctrl-C, puis transcrit + notes (affichées en JSON)
./.build/release/capteur

# durée fixe + langue + rangement direct dans la mémoire souveraine
./.build/release/capteur --secondes 1800 --langue fr --ranger memoire

# rangement dans un dossier (ex. dossier synchronisé par un drive)
./.build/release/capteur --ranger dossier --dossier "$HOME/Google Drive/Notes"
```

Variables d'env : `BRIQUE_URL` (défaut `http://localhost:5980`), `TRANSCRIPTION_KEY`
(si la brique exige une clé). La brique doit tourner (`docker compose up` dans le dossier parent).

## Ce qu'il fait, étape par étape

1. ScreenCaptureKit livre l'audio système + micro (Float32, 48 kHz) ;
2. downmix mono + mixage des deux sources, clampé ;
3. écriture d'un WAV 16-bit ;
4. `POST /notes` multipart → la brique transcrit en local (Whisper) et synthétise les notes ;
5. la réponse (transcription + notes) est imprimée ; avec `--ranger`, elle est aussi archivée.

> Repli sans cette voie native : un **périphérique audio virtuel** (BlackHole) + un
> *Aggregate Device* (BlackHole + micro), puis enregistrer avec ffmpeg/QuickTime et
> importer le fichier dans le front. La voie native ci-dessus évite d'installer quoi que ce soit.
