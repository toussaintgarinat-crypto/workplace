"""Config de test : DB temporaire + secret de session fixe AVANT tout import des modules."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "restaurant_test.db")
os.environ["RESTAURANT_DB"] = _db
os.environ.setdefault("RESTAURANT_SECRET", "secret-de-test-fixe")

if os.path.exists(_db):
    os.remove(_db)
