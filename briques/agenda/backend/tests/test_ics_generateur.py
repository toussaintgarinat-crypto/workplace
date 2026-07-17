"""S179 — générateur ICS pur (RFC 5545). Aucune I/O : on lui passe des dicts."""
from __future__ import annotations

from datetime import datetime

from services.ics import event_en_vevent, generer_ics


def _evt(**kw):
    base = {"uid": "e1", "title": "Dîner", "start": datetime(2026, 7, 20, 19, 0, 0),
            "end": datetime(2026, 7, 20, 21, 0, 0), "all_day": False,
            "description": None, "location": None, "rrule": None,
            "exdates": [], "recurrence_id": None}
    base.update(kw)
    return base


def test_squelette_vcalendar():
    out = generer_ics([_evt()])
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert out.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in out
    assert "BEGIN:VEVENT" in out and "END:VEVENT" in out
    assert "UID:e1" in out
    assert "SUMMARY:Dîner" in out
    assert "DTSTART:20260720T190000Z" in out
    assert "DTEND:20260720T210000Z" in out


def test_journee_entiere_value_date():
    out = generer_ics([_evt(all_day=True)])
    assert "DTSTART;VALUE=DATE:20260720" in out
    assert "DTEND;VALUE=DATE:20260720" in out


def test_recurrence_rrule_et_exdate():
    out = generer_ics([_evt(rrule="FREQ=WEEKLY;BYDAY=MO",
                            exdates=[datetime(2026, 7, 27, 19, 0, 0)])])
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO" in out
    assert "EXDATE:20260727T190000Z" in out


def test_override_recurrence_id():
    out = generer_ics([_evt(recurrence_id=datetime(2026, 7, 27, 19, 0, 0))])
    assert "RECURRENCE-ID:20260727T190000Z" in out


def test_echappement_rfc5545():
    out = generer_ics([_evt(title="A; B, C\\D", description="ligne1\nligne2",
                            location="12, rue X")])
    assert "SUMMARY:A\\; B\\, C\\\\D" in out
    assert "DESCRIPTION:ligne1\\nligne2" in out
    assert "LOCATION:12\\, rue X" in out
