"""Config de test : DB temporaire AVANT tout import des modules applicatifs."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "veille_info_test.db")
os.environ["VEILLE_INFO_DB"] = _db
os.environ.pop("API_KEYS", None)         # clés libres en test (isolation par empreinte)
os.environ.pop("GATEWAY_KEY", None)      # pas d'appel LLM réel : repli honnête testé
os.environ.pop("GATEWAY_URL", None)
os.environ.pop("VEILLE_INFO_KEY", None)  # /digest/executer ouvert en test

if os.path.exists(_db):
    os.remove(_db)
