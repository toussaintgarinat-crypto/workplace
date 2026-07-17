from datetime import datetime
from services.heures_calmes import dans_les_heures_calmes


def test_none_jamais_calme():
    assert dans_les_heures_calmes(None, datetime(2026, 7, 16, 3, 0)) is False


def test_plage_enjambe_minuit():
    p = "22:00-07:00"
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 23, 30)) is True
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 3, 0)) is True
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 12, 0)) is False


def test_plage_meme_jour():
    p = "09:00-17:00"
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 12, 0)) is True
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 20, 0)) is False
