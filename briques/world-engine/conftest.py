"""Config de test : DB temporaire + mode auth ouvert AVANT tout import des modules."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "world_engine_test.db")
os.environ["WORLD_ENGINE_DB"] = _db
os.environ.setdefault("API_KEYS", "")     # mode ouvert → tenant "public"
os.environ.setdefault("HORLOGE_SCHEDULER_DESACTIVE", "1")  # jamais de boucle de fond réelle en test

if os.path.exists(_db):
    os.remove(_db)
