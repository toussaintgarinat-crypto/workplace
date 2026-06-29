"""État partagé du Cœur.

Le registre des briques est instancié UNE fois ici, puis importé par main.py
(qui le `charge()` au démarrage via le lifespan) et par tous les routers. Avoir
ce singleton dans son propre module évite l'import circulaire main ↔ routers.
"""
from registre import Registre

registre = Registre()
