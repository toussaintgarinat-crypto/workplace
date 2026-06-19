"""Config de test : AUCUN fournisseur configuré → mode placeholder honnête déterministe.

On coupe le moteur local Piper ET toute clé hébergée AVANT le 1er import, pour que les tests
offline soient reproductibles quel que soit l'environnement du shell (sinon un binaire piper
présent + PIPER_VOICE, ou une vraie clé, rendrait un fournisseur « disponible »).
"""
import os

os.environ["API_KEYS"] = ""              # mode ouvert
os.environ["VOIX_LOCAL"] = "0"           # coupe le moteur souverain Piper (déterminisme)

for _v in ("VOIX_PROVIDERS", "PIPER_VOICE", "PIPER_BIN", "OPENAI_API_KEY",
           "ELEVENLABS_API_KEY", "GATEWAY_KEY"):
    os.environ.pop(_v, None)
