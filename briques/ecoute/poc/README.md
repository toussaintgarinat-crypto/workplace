# POC openWakeWord (S41)

Preuve go/no-go pour la détection de mot-clé « comme Siri ». **Décision : voir [`DECISION.md`](./DECISION.md).**

Ce dossier est un **POC**, pas la brique. La brique serveur `ecoute` (flux micro par WebSocket + fournisseur `creerWakeWord()` dans `core/main.py`) est l'incrément **S42**.

## Reproduire (~2 min, macOS)

```bash
cd briques/ecoute/poc

# 1. Environnement Python 3.11 (PAS 3.14 : wheels onnxruntime/numpy indisponibles)
/usr/local/opt/python@3.11/bin/python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Synthétiser les échantillons de test (TTS macOS `say` → WAV 16 kHz mono)
./synthese.sh

# 3. Lancer la détection (télécharge les modèles ONNX pré-entraînés au 1ᵉʳ run)
.venv/bin/python detection.py
```

Sortie attendue : les positifs « hey jarvis » se déclenchent (score > 0.8), les négatifs
restent silencieux (~0.000), **zéro faux positif**. Détail et limites dans `DECISION.md`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `synthese.sh` | Génère 11 WAV de test (positifs « hey jarvis », négatifs, noms FR) via `say` + `afconvert` |
| `detection.py` | Charge le modèle pré-entraîné `hey_jarvis` et le fait défiler sur les échantillons |
| `requirements.txt` | Dépendances épinglées (Python 3.11) |
| `DECISION.md` | **Le livrable** : analyse et décision go/no-go |
| `.venv/`, `echantillons/` | Générés, ignorés par git |
