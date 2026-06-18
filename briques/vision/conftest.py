"""Config de test : AUCUN moteur OCR configuré → mode repli honnête, déterministe.

On force l'absence de tout moteur AVANT le 1er import, pour que les tests offline soient
déterministes quel que soit l'environnement du shell :
  • VISION_LOCAL=0 désactive les moteurs souverains LOCAUX (même si markitdown/tesseract
    sont installés sur la machine de dev) ;
  • on retire toute clé hébergée (Mistral/Google) qui traînerait dans l'env.
Ainsi `disponibles()` est vide et le moteur rend son repli honnête, testable sans réseau.
"""
import os

os.environ["API_KEYS"] = ""               # mode ouvert
os.environ["VISION_LOCAL"] = "0"          # neutralise markitdown/tesseract en test

for _v in ("MISTRAL_API_KEY", "GOOGLE_VISION_API_KEY", "GOOGLE_API_KEY", "VISION_PROVIDERS"):
    os.environ.pop(_v, None)
