"""Fuseaux horaires — normalisation aux frontières de la brique.

Convention de **stockage** : datetime NAÏF en UTC. C'est déjà ce que rangent les
importateurs (Google `_parse_google_dt` et TimeTree `_from_ms` font tous deux
`.astimezone(UTC).replace(tzinfo=None)`). On garde cette convention unique en base.

La brique faisait deux erreurs symétriques sur cette frontière :

- en **entrée**, une heure naïve saisie par un humain (« 14:00 ») était stockée telle
  quelle comme si c'était de l'UTC — donc décalée du fuseau de Paris ;
- en **sortie**, l'UTC naïf était sérialisé sans offset, si bien que le navigateur
  (`new Date(...)`) et les lecteurs par découpage de chaîne (`[11:16]` du briefing et
  des rappels) l'interprétaient comme de l'heure locale → événements affichés en avance.

On corrige donc en un seul endroit :

- ENTRÉE (`vers_utc_naif`) : un datetime *aware* respecte son offset ; un datetime
  *naïf* est interprété comme l'heure murale d'**Europe/Paris** (l'humain saisit en
  local). Résultat : un naïf UTC, prêt à stocker.
- SORTIE (`vers_paris`) : on rattache **Europe/Paris** (avec offset) au naïf UTC stocké,
  pour que tout lecteur — JS comme découpage de chaîne — voie l'heure locale correcte,
  sans dépendre du fuseau du serveur. Les changements d'heure (été/hiver) sont gérés
  par `zoneinfo`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def vers_utc_naif(dt: datetime) -> datetime:
    """Heure entrante → naïf UTC (convention de stockage).

    Naïf = heure murale Europe/Paris ; aware = offset respecté."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def vers_paris(dt: datetime) -> datetime:
    """Heure stockée (naïf UTC) → aware Europe/Paris, pour l'affichage."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PARIS)
