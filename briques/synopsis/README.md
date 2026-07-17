# Synopsis Workplace

**Résumé vidéo YouTube par IA** — conçu pour fonctionner en standalone **ou** comme brique du projet [Workplace](https://github.com/anomalyco/youtube-summarizer).

## Quick Start

```bash
# Standalone
export OPENROUTER_API_KEY="sk-or-..."
pip install -r requirements.txt
python main.py

# Test — POST renvoie 202 + job_id, puis poll GET /jobs/{job_id} (voir Endpoints API)
curl -X POST http://localhost:6090/resumer -H "Content-Type: application/json" -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "langue": "Français"}'
```

## Mode Gateway (Workplace)

Quand la variable `GATEWAY_URL` est définie, Synopsis détecte automatiquement le Gateway Workplace et route tous les appels LLM via celui-ci :

```bash
export GATEWAY_URL="http://host.docker.internal:4001"
export GATEWAY_KEY="sk-wp-..."
python main.py
```

## Endpoints API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sante` | Health check (+ statut Gateway) |
| `POST` | `/resumer` | `{"url": "...", "langue": "Français"}` → `202 {job_id, statut:"en_cours", poll_url}` |
| `POST` | `/reel` | `{"url": "...", "duree_clip": 45}` → `202 {job_id, poll_url}` (highlight reel) |
| `POST` | `/resumer-fichier` | multipart `fichier=...` → `202 {job_id, poll_url}` |
| `GET` | `/jobs/{id}` | `{statut, progress_pct, resultat?, erreur?}` — poll jusqu'à `statut:"termine"\|"erreur"` |

Tous les POST sont **asynchrones** (S181) : la brique renvoie `202` immédiatement et
exécute le pipeline en arrière-plan (BackgroundTasks). Poller `GET /jobs/{job_id}`
jusqu'à `statut:"termine"` (résultat) ou `statut:"erreur"` (échec).

## Intégration Workplace

1. Copier ce dossier dans `~/Desktop/Workplace/briques/synopsis/`
2. `cd ~/Desktop/Workplace/briques/synopsis && make up`
3. `curl -X POST http://localhost:5000/briques/reload`
4. L'assistant IA Workplace auto-découvre les capacités `video_resumer` et `youtube_reel` (déclarées `async:true` : le Cœur sonde `GET /jobs/{id}` après le 202)

## Licence

MIT
