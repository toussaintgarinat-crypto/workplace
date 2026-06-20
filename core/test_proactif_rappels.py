"""Rappels d'agenda configurables — déclenchement proactif (côté Cœur).

Autonome : aucun réseau. On redirige la base des rappels vers un dossier temporaire et
on mocke `agenda.lister_evenements`. On vérifie : la logique de déclenchement pure
(_rappels_dus), le formatage du délai, le déclenchement par (événement, minutes) et
son dédoublonnage, et l'absence de rappel quand l'événement n'en configure aucun.
    $ cd core && python3 test_proactif_rappels.py
"""
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
    # Repart d'une base de rappels vierge à chaque test.
    db = os.environ["RAPPELS_DB"]
    if os.path.exists(db):
        os.remove(db)
    proactif.init_db()


def _evt(titre, dans_minutes, rappels, eid="e1", lieu=None):
    debut = datetime.now() + timedelta(minutes=dans_minutes)
    fin = debut + timedelta(hours=1)
    return {"id": eid, "title": titre, "start_at": debut.isoformat(),
            "end_at": fin.isoformat(), "location": lieu, "rappels": rappels}


def _mock_evts(evts):
    async def _faux(registre, debut=None, fin=None):
        return evts
    agenda.lister_evenements = _faux


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Logique pure ─────────────────────────────────────────────────────────────

def test_delai_lisible():
    assert proactif._delai_lisible(0) == "maintenant"
    assert proactif._delai_lisible(10) == "dans 10 min"
    assert proactif._delai_lisible(60) == "dans 1 h"
    assert proactif._delai_lisible(1440) == "dans 1 j"


def test_rappels_dus_fire_quand_du():
    maintenant = datetime(2030, 1, 1, 13, 50)        # 10 min avant 14:00
    evt = {"start_at": "2030-01-01T14:00:00", "rappels": [10, 1440]}
    dus = list(proactif._rappels_dus(evt, maintenant))
    # 10 min : fire_at=13:50 → dû. 1440 min : fire_at la veille → dû aussi.
    assert sorted(m for m, _ in dus) == [10, 1440]


def test_rappels_dus_pas_encore():
    maintenant = datetime(2030, 1, 1, 13, 40)        # 20 min avant → le rappel 10 min n'est pas dû
    evt = {"start_at": "2030-01-01T14:00:00", "rappels": [10]}
    assert list(proactif._rappels_dus(evt, maintenant)) == []


def test_rappels_dus_pas_apres_le_debut():
    maintenant = datetime(2030, 1, 1, 14, 5)         # événement déjà commencé
    evt = {"start_at": "2030-01-01T14:00:00", "rappels": [10]}
    assert list(proactif._rappels_dus(evt, maintenant)) == []


# ── Déclenchement de bout en bout (avec mock agenda) ─────────────────────────

def test_check_leve_un_rappel():
    _reset()
    _mock_evts([_evt("Dentiste", dans_minutes=9, rappels=[10])])
    n = _run(proactif._check_agenda(None))
    assert n == 1
    rappels = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(rappels) == 1 and "Dentiste" in rappels[0]["titre"]


def test_check_dedoublonne():
    _reset()
    _mock_evts([_evt("Dentiste", dans_minutes=9, rappels=[10])])
    assert _run(proactif._check_agenda(None)) == 1
    assert _run(proactif._check_agenda(None)) == 0     # 2ᵉ passage : pas de doublon


def test_check_plusieurs_rappels_meme_evt():
    _reset()
    # Événement à +9 min avec rappels 10 min ET 30 min : les deux sont dus → 2 rappels.
    _mock_evts([_evt("Réunion", dans_minutes=9, rappels=[10, 30])])
    assert _run(proactif._check_agenda(None)) == 2


def test_check_sans_rappels_ne_leve_rien():
    _reset()
    _mock_evts([_evt("Libre", dans_minutes=30, rappels=[])])
    assert _run(proactif._check_agenda(None)) == 0
    assert [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"] == []


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
