"""Config de test : stockage temporaire + AUCUN fournisseur configuré (mode placeholder).

On force l'absence de toute clé/URL de fournisseur AVANT le 1er import, pour que les tests
offline soient déterministes quel que soit l'environnement du shell (sinon une vraie
GATEWAY_KEY / clé hébergée traînant dans l'env rendrait un fournisseur « disponible »).
"""
import os
import tempfile

os.environ["IMAGES_DIR"] = os.path.join(tempfile.gettempdir(), "images_brique_test")
os.environ["API_KEYS"] = ""               # mode ouvert

# Tout fournisseur : non configuré → mode placeholder honnête.
for _v in ("COMFY_URL", "GATEWAY_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "FAL_KEY",
           "REPLICATE_API_TOKEN", "OPENAI_API_KEY", "PRUNA_API_KEY", "IMAGE_PROVIDERS"):
    os.environ.pop(_v, None)
