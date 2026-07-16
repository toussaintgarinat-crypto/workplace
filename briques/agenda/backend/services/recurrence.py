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


@dataclass
class Occurrence:
    """Une occurrence concrète d'un event. `source` = l'objet à rendre (le maître pour
    une occurrence virtuelle, l'event-override pour une occurrence modifiée). `start/end`
    = horaires effectifs. `occurrence_start` = RECURRENCE-ID : identité stable de
    l'occurrence (clé de dédup proactif, ancre du front)."""
    source: object
    start: datetime
    end: datetime
    occurrence_start: datetime
    recurrent: bool


def expanser(maitre, debut, fin, exdates, overrides) -> list[Occurrence]:
    """Déplie `maitre` sur [debut, fin]. Non récurrent → se renvoie tel quel. Récurrent →
    une Occurrence par date produite, en sautant `exdates` et en substituant `overrides`.
    Toutes les dates en naïf UTC. `debut`/`fin` None = pas de borne (le cap protège)."""
    if not maitre.recurrence_rule:
        if debut and maitre.end_at < debut:
            return []
        if fin and maitre.start_at > fin:
            return []
        return [Occurrence(maitre, maitre.start_at, maitre.end_at,
                           maitre.start_at, False)]

    duree = maitre.end_at - maitre.start_at
    regle = rrulestr(maitre.recurrence_rule, dtstart=maitre.start_at)
    # rrule.between est inclusif ; chaque borne est indépendante (`debut`/`fin` peuvent
    # être None séparément). Si `fin` est posé on peut appeler .between directement (borne
    # basse = debut - durée si `debut` posé, sinon le dtstart). Si `fin` est absent on doit
    # itérer nous-mêmes avec le cap MAX_OCCURRENCES, en sautant les occurrences qui se
    # terminent avant `debut` pour ne pas perdre cette borne-là.
    if fin is not None:
        borne_basse = (debut - duree) if debut is not None else maitre.start_at
        dates = regle.between(borne_basse, fin, inc=True)
    else:
        dates = []
        for i, d in enumerate(regle):
            if i >= MAX_OCCURRENCES:
                break
            if debut is not None and d + duree < debut:
                continue
            dates.append(d)
    occ: list[Occurrence] = []
    for d in dates[:MAX_OCCURRENCES]:
        if d in exdates:
            continue  # une exdate l'emporte sur un override à la même date (précédence voulue)
        ov = overrides.get(d)
        if ov is not None:
            occ.append(Occurrence(ov, ov.start_at, ov.end_at, d, True))
        else:
            occ.append(Occurrence(maitre, d, d + duree, d, True))
    return occ
