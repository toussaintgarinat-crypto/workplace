"""Config de test : DB temporaire AVANT tout import des modules de la brique."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "paiements_test.db")
os.environ["PAIEMENTS_DB"] = _db
os.environ.pop("STRIPE_SECRET_KEY", None)      # tests = mode mock honnête (jamais d'appel réel)
os.environ.pop("API_KEYS", None)               # clés libres en test (isolation par empreinte)

if os.path.exists(_db):
    os.remove(_db)
