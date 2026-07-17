"""Rend la lib partagée du monorepo (shared/) importable quand les tests de cette
brique tournent NATIVEMENT depuis ce dossier. En conteneur (Workplace ou dépôt
standalone Calendrier Familial), shared/ est déjà à côté du code — ce shim n'y sert
à rien et se désactive de lui-même si l'arborescence n'est pas celle du monorepo.
"""
import sys
from pathlib import Path

# briques/agenda/backend/conftest.py → racine du monorepo = 4 niveaux au-dessus.
# Hors monorepo (image standalone : /app/conftest.py), parents[3] n'existe pas : on
# ne fait alors rien — shared/ est déjà importable localement (cwd/PYTHONPATH=/app).
_parents = Path(__file__).resolve().parents
if len(_parents) > 3:
    _RACINE = _parents[3]
    if str(_RACINE) not in sys.path:
        sys.path.insert(0, str(_RACINE))
