"""Config de test : DB temporaire + secret de chiffrement AVANT tout import des modules."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "mail_test.db")
os.environ["MAIL_DB"] = _db
os.environ.setdefault("MAIL_VAULT_SECRET", "secret-de-test-non-confidentiel")  # chiffrement local
os.environ.pop("API_KEYS", None)        # clés libres en test (isolation par empreinte)
os.environ.pop("GATEWAY_KEY", None)     # pas d'appel LLM réel : repli honnête testé

if os.path.exists(_db):
    os.remove(_db)
