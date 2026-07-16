from __future__ import annotations

import pytest

from services.recurrence import valider_rrule


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
