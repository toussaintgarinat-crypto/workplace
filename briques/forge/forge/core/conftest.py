"""Rend la lib partagée du monorepo (shared/) importable quand les tests du core
Forge tournent NATIVEMENT depuis ce dossier. En conteneur, shared/ est copiée dans
/app par le Dockerfile (build-context = racine du repo) — ce shim n'y sert à rien.
"""
import sys
from pathlib import Path

# briques/forge/forge/core/conftest.py → racine du monorepo = 4 niveaux au-dessus.
_RACINE = Path(__file__).resolve().parents[4]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))
