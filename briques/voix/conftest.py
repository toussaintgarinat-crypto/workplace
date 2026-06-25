"""Config de test : AUCUN fournisseur configuré → mode placeholder honnête déterministe.

On coupe le moteur local Piper ET toute clé hébergée AVANT le 1er import, pour que les tests
offline soient reproductibles quel que soit l'environnement du shell (sinon un binaire piper
présent + PIPER_VOICE, ou une vraie clé, rendrait un fournisseur « disponible »).
"""
import os

os.environ["API_KEYS"] = ""              # mode ouvert
os.environ["VOIX_LOCAL"] = "0"           # coupe le moteur souverain Piper (déterminisme)

for _v in ("VOIX_PROVIDERS", "PIPER_VOICE", "PIPER_BIN", "OPENAI_API_KEY",
           "ELEVENLABS_API_KEY", "GATEWAY_KEY",
           # Chat vocal temps réel : aucune clé en test → relais inertes, déterministe.
           "VOIX_OPENAI_API_KEY", "VOIX_GOOGLE_API_KEY", "VOIX_XAI_API_KEY",
           "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "GROK_API_KEY",
           "VOIX_AGENT_NOM",
           # Moteurs locaux naturels OPT-IN : drapeaux coupés → inertes en test.
           "VOIX_KOKORO", "VOIX_COQUI"):
    os.environ.pop(_v, None)
