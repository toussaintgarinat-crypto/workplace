"""S174 — résolution des rappels effectifs d'un participant (pur)."""

from services.rappels import rappels_effectifs


def test_none_herite_du_defaut_event():
    assert rappels_effectifs(None, [10, 1440]) == [10, 1440]


def test_liste_vide_signifie_aucun():
    assert rappels_effectifs([], [10]) == []


def test_override_personnel():
    assert rappels_effectifs([60], [10]) == [60]
