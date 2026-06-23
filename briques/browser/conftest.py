"""Config de test : AUCUN moteur joignable → repli honnête, déterministe, hors-ligne.

On neutralise tout AVANT le 1er import pour que les tests offline soient déterministes
quel que soit l'environnement du shell :
  • SEARXNG_URL="" → SearXNG inactif (pas d'appel réseau accidentel) ;
  • BROWSER_DDG=0 → DuckDuckGo désactivé ;
  • on retire les clés des providers hébergés qui traîneraient.
Ainsi `providers.actifs()` est vide et /rechercher rend sa note honnête, sans réseau.
"""
import os

os.environ["API_KEYS"] = ""               # mode ouvert
os.environ["SEARXNG_URL"] = ""            # neutralise SearXNG en test
os.environ["BROWSER_DDG"] = "0"           # neutralise DuckDuckGo en test
os.environ["RECHERCHE_DDG"] = "0"         # idem via l'alias de compat

for _v in ("TAVILY_API_KEY", "BRAVE_API_KEY", "EXA_API_KEY", "SERPER_API_KEY",
           "SERPAPI_API_KEY", "KAGI_API_KEY", "BING_API_KEY",
           "BROWSER_PROVIDERS", "RECHERCHE_PROVIDERS"):
    os.environ.pop(_v, None)
