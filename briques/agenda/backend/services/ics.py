"""Générateur ICS (RFC 5545) — S179. PUR : prend des dicts/ORM, renvoie du texte, aucune
I/O. Les dates sont émises en UTC suffixe `Z` (events stockés en naïf UTC) ; `all_day` →
`VALUE=DATE`. La récurrence (`RRULE`/`EXDATE`) est émise TELLE QUELLE — le client agenda
l'expanse (comportement standard, robuste)."""
from __future__ import annotations

from datetime import datetime


def _echapper(texte: str) -> str:
    """Échappement RFC 5545 : backslash d'abord, puis ; , et retours ligne."""
    return (texte.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n").replace("\r", ""))


def _fmt_utc(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _ligne(cles: str, valeur: str) -> str:
    return f"{cles}:{valeur}"


def _vevent(e: dict) -> list[str]:
    lignes = ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{_fmt_utc(datetime.utcnow())}"]
    if e["all_day"]:
        lignes.append(f"DTSTART;VALUE=DATE:{_fmt_date(e['start'])}")
        lignes.append(f"DTEND;VALUE=DATE:{_fmt_date(e['end'])}")
    else:
        lignes.append(f"DTSTART:{_fmt_utc(e['start'])}")
        lignes.append(f"DTEND:{_fmt_utc(e['end'])}")
    lignes.append(_ligne("SUMMARY", _echapper(e["title"])))
    if e.get("description"):
        lignes.append(_ligne("DESCRIPTION", _echapper(e["description"])))
    if e.get("location"):
        lignes.append(_ligne("LOCATION", _echapper(e["location"])))
    if e.get("rrule"):
        lignes.append(f"RRULE:{e['rrule']}")
    if e.get("exdates"):
        if e["all_day"]:
            lignes.append("EXDATE;VALUE=DATE:" + ",".join(_fmt_date(d) for d in e["exdates"]))
        else:
            lignes.append("EXDATE:" + ",".join(_fmt_utc(d) for d in e["exdates"]))
    if e.get("recurrence_id"):
        if e["all_day"]:
            lignes.append(f"RECURRENCE-ID;VALUE=DATE:{_fmt_date(e['recurrence_id'])}")
        else:
            lignes.append(f"RECURRENCE-ID:{_fmt_utc(e['recurrence_id'])}")
    lignes.append("END:VEVENT")
    return lignes


def generer_ics(events: list[dict], nom_calendrier: str = "Agenda") -> str:
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Workplace//Agenda//FR",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
              _ligne("X-WR-CALNAME", _echapper(nom_calendrier))]
    for e in events:
        lignes.extend(_vevent(e))
    lignes.append("END:VCALENDAR")
    return "\r\n".join(lignes) + "\r\n"


def _as_dt(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


def event_en_vevent(e) -> dict:
    """Mappe un ORM `Event` vers le dict attendu par `generer_ics`. Un event override
    (recurrence_parent_id non-NULL) porte un `recurrence_id` = sa `recurrence_date`."""
    return {
        "uid": e.recurrence_parent_id or e.id,
        "title": e.title or "",
        "start": e.start_at,
        "end": e.end_at,
        "all_day": bool(e.all_day),
        "description": e.description,
        "location": e.location,
        "rrule": e.recurrence_rule,
        "exdates": [_as_dt(x) for x in (e.exdates or [])],
        "recurrence_id": e.recurrence_date if e.recurrence_parent_id else None,
    }
