"""Helpers de formatage à la française — parité des `toLocaleString('fr-FR')` du Bun.

Utilisés uniquement dans les **contenus markdown générés** (rapports/briefs).
Indépendants de l'ICU/locale système (pas de dépendance à `locale.setlocale`).
"""

from __future__ import annotations

import datetime

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre"]

# Node/ICU utilise le NARROW NO-BREAK SPACE (U+202F) comme séparateur de milliers
# en fr-FR, pas l'espace ASCII. On le réplique tel quel pour la parité du texte.
_THIN_NBSP = " "


def fr_date(dt: datetime.datetime) -> str:
    """toLocaleDateString('fr-FR') -> 'JJ/MM/AAAA'."""
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year}"


def fr_datetime(dt: datetime.datetime) -> str:
    """toLocaleString('fr-FR') -> 'JJ/MM/AAAA HH:MM:SS'."""
    return f"{fr_date(dt)} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def fr_date_long(dt: datetime.datetime, *, with_year: bool = True) -> str:
    """toLocaleDateString('fr-FR', {weekday:'long', day, month:'long'[, year]})."""
    base = f"{_JOURS[dt.weekday()]} {dt.day} {_MOIS[dt.month - 1]}"
    return f"{base} {dt.year}" if with_year else base


def fr_number(n: float | int) -> str:
    """toLocaleString('fr-FR') pour un entier (séparateur = U+202F)."""
    return f"{int(round(n)):,}".replace(",", _THIN_NBSP)
