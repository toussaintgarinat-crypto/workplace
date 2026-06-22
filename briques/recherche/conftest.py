"""Config de test : AUCUN moteur joignable → repli honnête, déterministe, hors-ligne.

On neutralise tout AVANT le 1er import pour que les tests offline soient déterministes
quel que soit l'environnement du shell :
  • SEARXNG_URL="" → SearXNG.disponible() = False (pas d'appel réseau accidentel) ;
  • RECHERCHE_DDG=0 → DuckDuckGo désactivé ;
  • on retire TAVILY_API_KEY / RECHERCHE_PROVIDERS qui traîneraient.
Ainsi `disponibles()` est vide et /rechercher rend sa note honnête, sans réseau.
"""
import os

os.environ["API_KEYS"] = ""               # mode ouvert
os.environ["SEARXNG_URL"] = ""            # neutralise SearXNG en test
os.environ["RECHERCHE_DDG"] = "0"         # neutralise DuckDuckGo en test

for _v in ("TAVILY_API_KEY", "RECHERCHE_PROVIDERS"):
    os.environ.pop(_v, None)
