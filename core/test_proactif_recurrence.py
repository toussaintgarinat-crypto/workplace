"""S175 — deux occurrences d'un même event récurrent (même id, occurrence_start
différent) doivent chacune notifier (clé de dédup par occurrence)."""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

_TMP = tempfile.mkdtemp()
os.environ["RAPPELS_DB"] = os.path.join(_TMP, "rappels.db")
sys.path.insert(0, os.path.dirname(__file__))

import agenda  # noqa: E402
import proactif  # noqa: E402


def _reset():
    if os.path.exists(proactif.DB):
        os.remove(proactif.DB)
    proactif.init_db()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_deux_occurrences_notifient_chacune():
    _reset()
    debut = datetime.now() + timedelta(minutes=9)
    base = {"id": "hebdo", "title": "Sport", "location": None,
            "end_at": (debut + timedelta(hours=1)).isoformat(), "rappels": [10],
            "participants": [{"user_id": "perso", "status": "accepted",
                              "rappels_effectifs": [10]}]}
    # Deux occurrences DUES du même maître, distinguées par occurrence_start.
    occ1 = {**base, "start_at": debut.isoformat(), "occurrence_start": debut.isoformat()}
    occ2b = debut + timedelta(minutes=1)
    occ2 = {**base, "start_at": occ2b.isoformat(), "occurrence_start": occ2b.isoformat()}

    async def _faux(registre, d=None, f=None):
        return [occ1, occ2]
    agenda.lister_evenements = _faux

    _run(proactif._check_agenda(None))
    badges = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(badges) == 2  # AVANT le fix : 1 seul (clé sans occurrence)


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
