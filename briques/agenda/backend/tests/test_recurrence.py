from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from services.horaires import PARIS
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
    """S175 fix (raffiné par FIX I4) : `fin=None` ne doit pas faire perdre la borne basse
    `debut` — le cap MAX_OCCURRENCES borne l'itération À PARTIR de `debut` (`rrule.xafter`),
    pas des MAX_OCCURRENCES premières dates depuis le dtstart du maître."""
    m = _maitre("FREQ=DAILY", jour=1)  # dtstart 2026-06-01 09:00, série sans fin
    debut = datetime(2026, 8, 1)
    occ = expanser(m, debut, None, set(), {})
    assert occ, "aucune occurrence retournée"
    assert all(o.start >= debut for o in occ)
    assert occ[0].start == datetime(2026, 8, 1, 9, 0)
    assert len(occ) == MAX_OCCURRENCES  # série infinie : le cap agit depuis `debut` (fix I4)


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


# ── FIX I3 : expansion en Europe/Paris, identités renvoyées en naïf UTC ────────

def test_expansion_paris_stable_au_changement_heure_ete():
    """FIX I3 : sans `tz`, une série hebdo à 09:00 UTC dérive en heure murale Paris
    de part et d'autre du changement d'heure (10h l'hiver, 11h l'été). Avec
    `tz=PARIS`, l'heure murale Paris reste 10:00 constante — donc l'UTC stocké
    bascule de 09:00 (hiver, avant le 29/03/2026) à 08:00 (été, après)."""
    d = datetime(2026, 3, 23, 9, 0)  # lundi 23/03/2026 09:00 UTC = 10:00 Paris (hiver)
    m = SimpleNamespace(start_at=d, end_at=d + timedelta(hours=1),
                        recurrence_rule="FREQ=WEEKLY")
    occ = expanser(m, datetime(2026, 3, 23), datetime(2026, 4, 6), set(), {}, tz=PARIS)
    par_date = {o.occurrence_start.date(): o for o in occ}
    # Le changement d'heure a lieu le dernier dimanche de mars (29/03/2026) : la
    # première occurrence (23/03) est encore en hiver, la seconde (30/03) en été.
    assert par_date[datetime(2026, 3, 23).date()].occurrence_start == datetime(2026, 3, 23, 9, 0)
    assert par_date[datetime(2026, 3, 30).date()].occurrence_start == datetime(2026, 3, 30, 8, 0)


def test_expansion_sans_tz_comportement_inchange():
    """Non-régression : `tz=None` (défaut) doit reproduire EXACTEMENT le comportement
    pur historique — aucune conversion, l'heure UTC stockée reste constante."""
    m = _maitre("FREQ=WEEKLY", jour=1)
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30), set(), {})
    debuts = [o.start for o in occ]
    assert debuts == [datetime(2026, 6, d, 9, 0) for d in (1, 8, 15, 22, 29)]


# ── FIX I4 : fenêtre ouverte (fin=None) avec `debut` doit partir de la fenêtre ──

def test_fin_none_avec_debut_ancien_part_de_la_fenetre():
    """FIX I4 : une série quotidienne démarrée en 2020, expansée avec `debut=2026-06-01`
    et `fin=None`, doit renvoyer MAX_OCCURRENCES occurrences à PARTIR de la fenêtre —
    pas les 366 premières de la série (toutes avant `debut`, donc 0 résultat)."""
    d = datetime(2020, 1, 1, 9, 0)
    m = SimpleNamespace(start_at=d, end_at=d + timedelta(hours=1),
                        recurrence_rule="FREQ=DAILY")
    debut = datetime(2026, 6, 1)
    occ = expanser(m, debut, None, set(), {})
    assert len(occ) == MAX_OCCURRENCES
    assert occ[0].start == datetime(2026, 6, 1, 9, 0)
    assert all(o.start >= debut for o in occ)
