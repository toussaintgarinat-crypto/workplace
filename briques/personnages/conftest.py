"""Config de test : DB temporaire + mode auth ouvert AVANT tout import des modules."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "personnages_test.db")
os.environ["PERSONNAGES_DB"] = _db
os.environ.setdefault("API_KEYS", "")     # mode ouvert → tenant "public"

if os.path.exists(_db):
    os.remove(_db)
