"""S174 — rappels par personne (côté Cœur) : un push messagerie par participant dû,
badge 🔔 réservé au propriétaire local, dédoublonnage par (event, user, minutes)."""

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


def _evt_participants(dans_minutes, participants, eid="e1"):
    debut = datetime.now() + timedelta(minutes=dans_minutes)
    return {"id": eid, "title": "Diner", "start_at": debut.isoformat(),
            "end_at": (debut + timedelta(hours=1)).isoformat(),
            "location": None, "rappels": [], "participants": participants}


def _mock_evts(evts):
    async def _faux(registre, debut=None, fin=None):
        return evts
    agenda.lister_evenements = _faux


def _capturer_push():
    pushes = []
    async def _faux(registre, titre, corps, utilisateur=None):
        pushes.append(utilisateur)
    proactif._pousser_messagerie = _faux
    return pushes


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_push_par_participant():
    _reset()
    pushes = _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": [10]},
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])])
    _run(proactif._check_agenda(None))
    assert sorted(pushes) == ["marina", "perso"]  # les deux notifiés


def test_badge_reserve_au_proprietaire():
    _reset()
    _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": [10]},
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])])
    _run(proactif._check_agenda(None))
    badges = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(badges) == 1  # seul « perso » a une pastille visible


def test_dedoublonnage_par_personne():
    _reset()
    _capturer_push()
    evt = [_evt_participants(9, [
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])]
    _mock_evts(evt)
    _run(proactif._check_agenda(None))
    pushes2 = _capturer_push()
    _run(proactif._check_agenda(None))
    assert pushes2 == []  # 2ᵉ passage : pas de re-push pour marina


def test_rappels_effectifs_respectes():
    _reset()
    pushes = _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": []},      # aucun
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},   # dû
    ])])
    _run(proactif._check_agenda(None))
    assert pushes == ["marina"]  # perso n'a aucun rappel


def test_repli_event_sans_participants():
    # Rétro-compat : un event legacy sans clé `participants` retombe sur perso + event.rappels.
    _reset()
    pushes = _capturer_push()
    debut = datetime.now() + timedelta(minutes=9)
    _mock_evts([{"id": "old", "title": "Legacy", "start_at": debut.isoformat(),
                 "end_at": (debut + timedelta(hours=1)).isoformat(),
                 "location": None, "rappels": [10]}])
    _run(proactif._check_agenda(None))
    assert pushes == ["perso"]
    badges = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(badges) == 1


def test_dedup_pousse_invisible_dans_lister():
    # Bug S174 Task 7 : _dedup_pousse trace une ligne "agenda-push" (vu=1, titre/corps
    # vides) pour ne pas re-pousser à un participant non-propriétaire (marina). Cette
    # ligne de bookkeeping ne doit JAMAIS remonter dans lister() — c'est ce que
    # /assistant/rappels et le panneau 🔔 du dashboard appellent (args par défaut).
    _reset()
    _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": [10]},
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])])
    _run(proactif._check_agenda(None))
    rows = proactif.lister()  # args par défaut, comme /assistant/rappels
    dedup = [r for r in rows if r.get("type") == "agenda-push"]
    assert dedup == []  # la ligne de dédup de marina ne doit jamais apparaître
    badges = [r for r in rows if r.get("type") == "agenda"]
    assert len(badges) == 1  # le vrai rappel du propriétaire reste visible


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
