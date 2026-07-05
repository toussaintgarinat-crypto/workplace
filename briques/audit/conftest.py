"""Rend la lib partagée du monorepo (shared/) importable quand les tests de cette
brique tournent NATIVEMENT depuis ce dossier. En conteneur, shared/ est copiée dans
/app par le Dockerfile (build-context = racine du repo) — ce shim n'y sert à rien.
"""
import sys
from pathlib import Path

_BRIQUE = Path(__file__).resolve().parent
_RACINE = _BRIQUE.parent.parent.parent
for _p in (_BRIQUE, _RACINE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
