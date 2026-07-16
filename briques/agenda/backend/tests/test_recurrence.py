from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from services.recurrence import valider_rrule, expanser, Occurrence, MAX_OCCURRENCES


def test_valide_weekly_byday():
    assert valider_rrule("FREQ=WEEKLY;BYDAY=MO") == "FREQ=WEEKLY;BYDAY=MO"


def test_strip_prefixe_rrule():
    assert valider_rrule("RRULE:FREQ=DAILY") == "FREQ=DAILY"


def test_rejette_freq_absent():
    with pytest.raises(ValueError):
        valider_rrule("INTERVAL=2")


def test_rejette_freq_trop_fine():
    with pytest.raises(ValueError):
        valider_rrule("FREQ=MINUTELY")


def test_rejette_garbage():
    with pytest.raises(ValueError):
        valider_rrule("pas une rrule du tout ###")


def _maitre(rule, jour=1, h=9):
    d = datetime(2026, 6, jour, h, 0)
    return SimpleNamespace(start_at=d, end_at=d + timedelta(hours=1),
                           recurrence_rule=rule)


def test_non_recurrent_se_renvoie():
    m = _maitre(None)
    occ = expanser(m, None, None, set(), {})
    assert len(occ) == 1
    assert occ[0].source is m and occ[0].recurrent is False
    assert occ[0].occurrence_start == m.start_at


def test_weekly_dans_fenetre():
    m = _maitre("FREQ=WEEKLY", jour=1)  # lundi 1er juin 2026
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30), set(), {})
    debuts = [o.start for o in occ]
    assert debuts == [datetime(2026, 6, d, 9, 0) for d in (1, 8, 15, 22, 29)]
    assert all(o.end - o.start == timedelta(hours=1) for o in occ)  # durée conservée
    assert all(o.recurrent for o in occ)


def test_exdate_saute_une_occurrence():
    m = _maitre("FREQ=WEEKLY", jour=1)
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30),
                   {datetime(2026, 6, 8, 9, 0)}, {})
    assert datetime(2026, 6, 8, 9, 0) not in [o.start for o in occ]
    assert len(occ) == 4


def test_override_remplace_l_occurrence():
    m = _maitre("FREQ=WEEKLY", jour=1)
    ov = SimpleNamespace(start_at=datetime(2026, 6, 8, 14, 0),   # déplacé à 14h
                         end_at=datetime(2026, 6, 8, 15, 0), recurrence_rule=None)
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30),
                   set(), {datetime(2026, 6, 8, 9, 0): ov})
    par_date = {o.occurrence_start: o for o in occ}
    remplacee = par_date[datetime(2026, 6, 8, 9, 0)]
    assert remplacee.source is ov and remplacee.start.hour == 14


def test_count_et_cap():
    m = _maitre("FREQ=DAILY", jour=1)
    occ = expanser(m, None, None, set(), {})   # série sans fin → cap
    assert len(occ) == 366


def test_borne_unique_debut_seul_sans_fin():
    """S175 fix : `fin=None` ne doit pas faire perdre la borne basse `debut` —
    avant fix, ce cas tombait dans la branche non bornée et repartait du dtstart."""
    m = _maitre("FREQ=DAILY", jour=1)  # dtstart 2026-06-01 09:00, série sans fin
    debut = datetime(2026, 8, 1)
    occ = expanser(m, debut, None, set(), {})
    assert occ, "aucune occurrence retournée"
    assert all(o.start >= debut for o in occ)
    assert occ[0].start == datetime(2026, 8, 1, 9, 0)
    assert len(occ) < MAX_OCCURRENCES  # le cap borne l'itération, pas seulement la sortie


def test_borne_unique_fin_seule_sans_debut():
    """S175 fix : `debut=None` avec `fin` posé doit borner par le haut dès le dtstart."""
    m = _maitre("FREQ=WEEKLY", jour=1)  # lundi 1er juin 2026
    fin = datetime(2026, 6, 30)
    occ = expanser(m, None, fin, set(), {})
    debuts = [o.start for o in occ]
    assert debuts == [datetime(2026, 6, d, 9, 0) for d in (1, 8, 15, 22, 29)]
    assert all(o.start <= fin for o in occ)


def test_non_recurrent_hors_fenetre_borne_unique():
    m = _maitre(None, jour=1)  # 2026-06-01 09h-10h, non récurrent
    occ = expanser(m, datetime(2026, 7, 1), None, set(), {})
    assert occ == []
