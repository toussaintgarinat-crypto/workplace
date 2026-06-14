"""Config de test : stockage temporaire + AUCUN fournisseur configuré (mode placeholder).

On force l'absence de toute clé de fournisseur AVANT le 1er import, pour que les tests
offline soient déterministes quel que soit l'environnement du shell (sinon une vraie
GATEWAY_KEY / clé hébergée traînant dans l'env rendrait un fournisseur « disponible »).
"""
import os
import tempfile

os.environ["VIDEOS_DIR"] = os.path.join(tempfile.gettempdir(), "videos_brique_test")
os.environ["API_KEYS"] = ""               # mode ouvert

# Tout fournisseur : non configuré → mode placeholder honnête.
for _v in ("FAL_KEY", "REPLICATE_API_TOKEN", "LUMAAI_API_KEY", "RUNWAY_API_KEY",
           "GATEWAY_KEY", "VIDEO_PROVIDERS"):
    os.environ.pop(_v, None)
