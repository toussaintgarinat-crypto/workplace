"""Config de test : DB temporaire AVANT tout import des modules (S184, motif mail/conftest.py)."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "ecoute_test.db")
os.environ["COMMANDES_DB"] = _db
os.environ.pop("ECOUTE_KEY", None)  # mode ouvert par défaut ; test_isolation.py la fixe elle-même

if os.path.exists(_db):
    os.remove(_db)
