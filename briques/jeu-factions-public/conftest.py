"""Config de test : DB temporaire + secrets de test AVANT tout import des modules."""
import os
import tempfile

import pytest

_db = os.path.join(tempfile.gettempdir(), "jeu_factions_public_test.db")
os.environ["JEU_FACTIONS_PUBLIC_DB"] = _db
os.environ.setdefault("JEU_FACTIONS_PUBLIC_SECRET", "cle-test-jeu-factions-public")
os.environ.setdefault("PERSONNAGES_URL", "http://personnages-test.invalid")
os.environ["JEU_FACTIONS_COMBAT_AUTOSTART"] = "0"    # jamais de vraie boucle temps réel en test

if os.path.exists(_db):
    os.remove(_db)


@pytest.fixture(autouse=True)
def _clear_db_before_test():
    if os.path.exists(_db):
        os.remove(_db)


@pytest.fixture(autouse=True)
def _vider_instances_combat():
    import combat
    combat._INSTANCES.clear()
    yield
    combat._INSTANCES.clear()


@pytest.fixture(autouse=True)
def _vider_limiteur():
    import limiteur
    limiteur._reinitialiser()
    yield
    limiteur._reinitialiser()
