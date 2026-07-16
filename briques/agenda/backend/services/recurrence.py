"""Récurrence RRULE (S175) — module PUR : validation + expansion en occurrences.

Aucune dépendance projet (pas de schémas ni d'ORM concret hors typing) pour rester
testable isolément et éviter tout cycle d'import. Toutes les dates manipulées sont en
NAÏF UTC (convention de stockage de la brique)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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


def expanser(maitre, debut, fin, exdates, overrides, tz=None) -> list[Occurrence]:
    """Déplie `maitre` sur [debut, fin]. Non récurrent → se renvoie tel quel. Récurrent →
    une Occurrence par date produite, en sautant `exdates` et en substituant `overrides`.
    Toutes les IDENTITÉS externes (occurrence_start, start, end, clés exdate/override)
    restent en naïf UTC — c'est la convention de stockage de la brique.

    `tz` (FIX I3, S175 review) : `None` (défaut) = comportement historique, la règle est
    dépliée directement sur l'UTC naïf stocké — l'heure murale Paris DÉRIVE de ±1h aux
    changements d'heure (une heure d'été/hiver). Un tzinfo (ex. `Europe/Paris`) = la règle
    est dépliée en heure LOCALE (heure murale constante, ex. « tous les lundis 10h » reste
    10h été comme hiver) ; chaque date produite est reconvertie en naïf UTC avant d'être
    exposée, donc l'appelant ne voit jamais de l'heure locale.

    `debut`/`fin` None = pas de borne (le cap MAX_OCCURRENCES protège). FIX I4 (S175
    review) : quand `fin` est absent mais `debut` est posé, on repart de `debut` (via
    `rrule.xafter`) plutôt que des `MAX_OCCURRENCES` premières dates depuis le dtstart du
    maître — sinon une vieille série (dtstart des années avant `debut`) ne renvoie rien,
    le cap étant épuisé bien avant d'atteindre la fenêtre demandée."""
    if not maitre.recurrence_rule:
        if debut and maitre.end_at < debut:
            return []
        if fin and maitre.start_at > fin:
            return []
        return [Occurrence(maitre, maitre.start_at, maitre.end_at,
                           maitre.start_at, False)]

    duree = maitre.end_at - maitre.start_at

    if tz is None:
        dtstart_local, debut_local, fin_local = maitre.start_at, debut, fin
        to_utc = lambda d_local: d_local
    else:
        def _vers_local(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)

        dtstart_local = _vers_local(maitre.start_at)
        debut_local = _vers_local(debut) if debut is not None else None
        fin_local = _vers_local(fin) if fin is not None else None

        def to_utc(d_local: datetime) -> datetime:
            return d_local.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)

    regle = rrulestr(maitre.recurrence_rule, dtstart=dtstart_local)
    # rrule.between est inclusif ; chaque borne est indépendante (`debut`/`fin` peuvent
    # être None séparément). Si `fin` est posé on peut appeler .between directement (borne
    # basse = debut - durée si `debut` posé, sinon le dtstart). Si `fin` est absent MAIS
    # `debut` est posé (FIX I4), `rrule.xafter` repart directement de la fenêtre demandée —
    # jamais des `MAX_OCCURRENCES` premières dates du dtstart, qui peuvent être toutes
    # antérieures à `debut` pour une vieille série. Si les deux bornes sont absentes, on
    # garde le comportement historique : les MAX_OCCURRENCES premières dates du dtstart.
    if fin_local is not None:
        borne_basse_local = (debut_local - duree) if debut_local is not None else dtstart_local
        dates_locales = regle.between(borne_basse_local, fin_local, inc=True)
    elif debut_local is not None:
        dates_locales = list(regle.xafter(debut_local - duree, count=MAX_OCCURRENCES, inc=True))
    else:
        dates_locales = []
        for i, d in enumerate(regle):
            if i >= MAX_OCCURRENCES:
                break
            dates_locales.append(d)
    occ: list[Occurrence] = []
    for d_local in dates_locales[:MAX_OCCURRENCES]:
        start_utc = to_utc(d_local)
        if start_utc in exdates:
            continue  # une exdate l'emporte sur un override à la même date (précédence voulue)
        ov = overrides.get(start_utc)
        if ov is not None:
            occ.append(Occurrence(ov, ov.start_at, ov.end_at, start_utc, True))
        else:
            occ.append(Occurrence(maitre, start_utc, start_utc + duree, start_utc, True))
    return occ
