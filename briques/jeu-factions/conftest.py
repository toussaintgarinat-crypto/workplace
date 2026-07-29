"""Config de test : DB temporaire + mode auth ouvert AVANT tout import des modules."""
import os
import tempfile

import pytest

_db = os.path.join(tempfile.gettempdir(), "jeu_factions_test.db")
os.environ["JEU_FACTIONS_DB"] = _db
os.environ.setdefault("API_KEYS", "")               # mode ouvert → tenant "public"
os.environ.setdefault("PERSONNAGES_URL", "http://personnages-test.invalid")
os.environ["JEU_FACTIONS_TICK_AUTOSTART"] = "0"      # jamais de boucle asyncio réelle en test

if os.path.exists(_db):
    os.remove(_db)


@pytest.fixture(autouse=True)
def _clear_db_before_test():
    """Clears the database before each test to ensure isolation."""
    if os.path.exists(_db):
        os.remove(_db)
