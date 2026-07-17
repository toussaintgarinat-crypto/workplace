"""Heures calmes (S178) : plage « HH:MM-HH:MM » pendant laquelle on ne notifie pas.
Pur, sans I/O. Gère l'enjambement de minuit (22:00-07:00)."""
from __future__ import annotations

from datetime import datetime


def dans_les_heures_calmes(plage: str | None, maintenant: datetime) -> bool:
    if not plage or "-" not in plage:
        return False
    try:
        deb, fin = plage.split("-", 1)
        hd, md = (int(x) for x in deb.strip().split(":"))
        hf, mf = (int(x) for x in fin.strip().split(":"))
    except (ValueError, TypeError):
        return False
    m = maintenant.hour * 60 + maintenant.minute
    d = hd * 60 + md
    f = hf * 60 + mf
    if d == f:
        return False
    if d < f:                       # même jour : [d, f)
        return d <= m < f
    return m >= d or m < f          # enjambe minuit
