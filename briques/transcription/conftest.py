"""Config de test : AUCUN fournisseur configuré → mode placeholder honnête déterministe.

On coupe le moteur local ET toute clé hébergée AVANT le 1er import, pour que les tests
offline soient reproductibles quel que soit l'environnement du shell (sinon une vraie
clé / faster-whisper installé rendrait un fournisseur « disponible »).
"""
import os

os.environ["API_KEYS"] = ""                  # mode ouvert
os.environ["TRANSCRIPTION_LOCAL"] = "0"      # coupe le moteur souverain local (déterminisme)

for _v in ("TRANSCRIPTION_PROVIDERS", "OPENAI_API_KEY", "DEEPGRAM_API_KEY",
           "ASSEMBLYAI_API_KEY", "GATEWAY_KEY", "DIARISATION_LOCAL", "HF_TOKEN"):
    os.environ.pop(_v, None)
