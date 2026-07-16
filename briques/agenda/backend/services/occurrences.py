"""Orchestration de la récurrence (S175) : charge maîtres + overrides + exdates depuis
la base et délègue l'expansion pure à `services.recurrence`. Point d'entrée READ des
occurrences (dashboard, agrégation, list_events). Toujours en naïf UTC en interne."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Event
from models.schemas import EventOut
from services.horaires import vers_paris, vers_utc_naif
from services.recurrence import Occurrence, expanser


def _naif(dt: datetime | str) -> datetime:
    """exdates/recurrence_date peuvent revenir en str (JSON) → datetime naïf UTC."""
    return datetime.fromisoformat(dt) if isinstance(dt, str) else dt


async def occurrences_calendrier(db: AsyncSession, cal_id: str,
                                 debut: datetime | None, fin: datetime | None) -> list[Occurrence]:
    """Occurrences d'un calendrier sur [debut, fin]. Les OVERRIDES ne sont jamais
    interrogés directement (recurrence_parent_id IS NULL) : ils sont réinjectés par
    l'expansion à la place de l'occurrence qu'ils remplacent."""
    d = vers_utc_naif(debut) if debut else None
    f = vers_utc_naif(fin) if fin else None
    # Non-récurrents chevauchant la fenêtre OU tout maître récurrent pouvant l'atteindre
    # (start_at <= fin ; une série ne produit rien avant son premier début).
    non_recurrent = [Event.recurrence_rule.is_(None)]
    if f:
        non_recurrent.append(Event.start_at <= f)
    if d:
        non_recurrent.append(Event.end_at >= d)
    recurrent = [Event.recurrence_rule.is_not(None)]
    if f:
        recurrent.append(Event.start_at <= f)
    rows = (await db.execute(
        select(Event).where(and_(
            Event.calendar_id == cal_id,
            Event.recurrence_parent_id.is_(None),
            or_(and_(*non_recurrent), and_(*recurrent)),
        )).order_by(Event.start_at)
    )).scalars().all()
    maitres = list(rows)
    ids = [m.id for m in maitres if m.recurrence_rule]
    overrides_par_parent: dict[str, dict[datetime, Event]] = {}
    if ids:
        ovs = (await db.execute(
            select(Event).where(Event.recurrence_parent_id.in_(ids))
        )).scalars().all()
        for ov in ovs:
            overrides_par_parent.setdefault(ov.recurrence_parent_id, {})[
                _naif(ov.recurrence_date)] = ov
    result: list[Occurrence] = []
    for m in maitres:
        exd = {_naif(x) for x in (m.exdates or [])}
        result.extend(expanser(m, d, f, exd, overrides_par_parent.get(m.id, {})))
    result.sort(key=lambda o: o.start)
    return result


def occurrence_en_dict(occ: Occurrence) -> dict:
    """Occurrence → dict JSON, à partir de EventOut de sa source, avec horaires et
    identité d'occurrence corrigés. Base commune au dashboard et à list_events."""
    dico = EventOut.model_validate(occ.source).model_dump(mode="json")
    dico["start_at"] = vers_paris(occ.start).isoformat()
    dico["end_at"] = vers_paris(occ.end).isoformat()
    dico["occurrence_start"] = vers_paris(occ.occurrence_start).isoformat()
    dico["recurrent"] = occ.recurrent
    return dico
