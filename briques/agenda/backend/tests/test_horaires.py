"""Fuseaux horaires — normalisation aux frontières (entrée naïf Paris / sortie Paris).

Vérifie le cœur du correctif : une heure saisie en heure locale est stockée en UTC
naïf, et ressort en Europe/Paris (avec offset) — round-trip stable, été comme hiver.
    $ cd backend && python3 -m pytest tests/test_horaires.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.schemas import EventCreate, EventOut
from services.horaires import vers_paris, vers_utc_naif


# ── Helper pur ───────────────────────────────────────────────────────────────

def test_naif_interprete_comme_paris_ete():
    # 14:00 saisi un jour d'été (Paris = UTC+2) → 12:00 UTC stocké.
    assert vers_utc_naif(datetime(2026, 6, 25, 14, 0)) == datetime(2026, 6, 25, 12, 0)


def test_naif_interprete_comme_paris_hiver():
    # 14:00 saisi un jour d'hiver (Paris = UTC+1) → 13:00 UTC stocké.
    assert vers_utc_naif(datetime(2026, 1, 15, 14, 0)) == datetime(2026, 1, 15, 13, 0)


def test_aware_respecte_son_offset():
    # Le front envoie déjà de l'UTC (Z) → conservé tel quel en naïf UTC.
    aware = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    assert vers_utc_naif(aware) == datetime(2026, 6, 25, 12, 0)


def test_sortie_rattache_paris():
    # Stocké 12:00 UTC → exposé 14:00+02:00 en été.
    sortie = vers_paris(datetime(2026, 6, 25, 12, 0))
    assert sortie.hour == 14 and sortie.utcoffset().total_seconds() == 2 * 3600


def test_round_trip_stable():
    saisi = datetime(2026, 6, 25, 14, 0)
    assert vers_paris(vers_utc_naif(saisi)).replace(tzinfo=None) == saisi


# ── Schémas (entrée + sortie) ────────────────────────────────────────────────

def test_event_create_normalise_en_utc():
    ec = EventCreate(calendar_id="c1", title="RDV",
                     start_at=datetime(2026, 6, 25, 14, 0),
                     end_at=datetime(2026, 6, 25, 15, 0))
    assert ec.start_at == datetime(2026, 6, 25, 12, 0)  # naïf UTC, sans tz
    assert ec.start_at.tzinfo is None


def test_event_out_serialise_en_paris():
    out = EventOut(id="e1", calendar_id="c1", title="RDV", description=None,
                   start_at=datetime(2026, 6, 25, 12, 0),   # stocké UTC naïf
                   end_at=datetime(2026, 6, 25, 13, 0),
                   location=None, color=None, all_day=False, recurrence_rule=None,
                   created_by="perso", created_at=datetime(2026, 6, 25, 12, 0),
                   updated_at=datetime(2026, 6, 25, 12, 0))
    js = out.model_dump(mode="json")
    assert js["start_at"].startswith("2026-06-25T14:00:00") and "+02:00" in js["start_at"]
