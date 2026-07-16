"""Récurrence RRULE (S175) — module PUR : validation + expansion en occurrences.

Aucune dépendance projet (pas de schémas ni d'ORM concret hors typing) pour rester
testable isolément et éviter tout cycle d'import. Toutes les dates manipulées sont en
NAÏF UTC (convention de stockage de la brique)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dateutil.rrule import rrulestr

MAX_OCCURRENCES = 366  # cap de sécurité : jamais expanser une série sans borne au-delà.

_FREQ_INTERDITES = ("SECONDLY", "MINUTELY", "HOURLY")  # bruit pour un agenda humain


def valider_rrule(rule: str) -> str:
    """Valide/normalise une RRULE. Renvoie la règle sans préfixe `RRULE:`.
    Lève ValueError si illisible, sans FREQ, ou d'une fréquence trop fine."""
    if not rule or not rule.strip():
        raise ValueError("règle de récurrence vide")
    nettoyee = rule.strip()
    if nettoyee.upper().startswith("RRULE:"):
        nettoyee = nettoyee[len("RRULE:"):]
    haut = nettoyee.upper()
    if "FREQ=" not in haut:
        raise ValueError("RRULE sans FREQ")
    if any(f"FREQ={f}" in haut for f in _FREQ_INTERDITES):
        raise ValueError("fréquence trop fine (max : quotidienne)")
    try:
        # dtstart bidon juste pour valider la grammaire ; on ne garde pas l'objet.
        rrulestr(nettoyee, dtstart=datetime(2000, 1, 1))
    except (ValueError, TypeError) as ex:
        raise ValueError(f"RRULE invalide : {ex}") from ex
    return nettoyee
