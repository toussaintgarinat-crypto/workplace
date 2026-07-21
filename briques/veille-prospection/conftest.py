"""Config de test : DB temporaire AVANT tout import des modules applicatifs."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "veille_prospection_test.db")
os.environ["VEILLE_PROSPECTION_DB"] = _db
os.environ.pop("API_KEYS", None)
os.environ.pop("GEO_KEY", None)
os.environ.pop("FORGE_KEY", None)
os.environ.pop("MEMOIRE_KEY", None)
os.environ.pop("VEILLE_PROSPECTION_KEY", None)

if os.path.exists(_db):
    os.remove(_db)
