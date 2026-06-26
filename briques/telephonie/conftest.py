"""Config de test : DB temporaire AVANT tout import des modules de la brique."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "telephonie_test.db")
os.environ["TELEPHONIE_DB"] = _db
os.environ.pop("TWILIO_ACCOUNT_SID", None)     # tests = mode mock honnête (jamais d'appel réel)
os.environ.pop("TWILIO_AUTH_TOKEN", None)
os.environ.pop("API_KEYS", None)               # clés libres en test (isolation par empreinte)

if os.path.exists(_db):
    os.remove(_db)
