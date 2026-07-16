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


# ── Écriture par portée (S175) : scope=this isole une occurrence sans toucher au
# maître ; scope=all (comportement historique) agit sur la série entière. ──────────

def occurrence_valide(maitre, occurrence: datetime) -> bool:
    """Vrai si `occurrence` (naïf UTC) est une occurrence produite par la règle du
    maître et pas déjà dans ses exdates."""
    if not maitre.recurrence_rule:
        return False
    exd = {_naif(x) for x in (maitre.exdates or [])}
    if occurrence in exd:
        return False
    petit = expanser(maitre, occurrence, occurrence, set(), {})
    return any(o.occurrence_start == occurrence for o in petit)


async def exclure_occurrence(db: AsyncSession, maitre: Event, occurrence: datetime) -> None:
    """Ajoute `occurrence` aux exdates du maître (réassignation : SQLAlchemy ne traque
    pas la mutation en place d'une colonne JSON). Supprime aussi un éventuel override
    de cette occurrence : sans ça il resterait une ligne morte (invisible car l'exdate
    prime dans l'expansion) qui ressurgirait si l'exdate était un jour retirée."""
    ov = (await db.execute(
        select(Event).where(and_(Event.recurrence_parent_id == maitre.id,
                                 Event.recurrence_date == occurrence))
    )).scalar_one_or_none()
    if ov is not None:
        await db.delete(ov)
    maitre.exdates = list(maitre.exdates or []) + [occurrence.isoformat()]
    await db.commit()


def occurrence_naive(occurrence: datetime | None) -> datetime | None:
    """`occurrence` (query ?scope=this) IDENTIFIE une occurrence déjà stockée — ce
    n'est pas une saisie humaine. Un client réel le renvoie AWARE (l'ISO Europe/Paris
    exposé par `occurrence_en_dict`/`vers_paris`) : on le reconvertit alors en naïf UTC
    via `vers_utc_naif`. Un naïf reçu tel quel (appel direct hors HTTP, ex. tests) est
    déjà dans la convention de stockage et n'est PAS réinterprété comme heure murale
    Paris — sinon un décalage DST (été/hiver) le ferait manquer sa propre occurrence."""
    if occurrence is None:
        return None
    return vers_utc_naif(occurrence) if occurrence.tzinfo is not None else occurrence


async def creer_ou_maj_override(db: AsyncSession, maitre: Event, occurrence: datetime,
                                champs: dict) -> Event:
    """Crée (ou met à jour) l'event-override d'une occurrence. `champs` = colonnes ORM à
    poser (title/start_at/end_at/...). Défaut : hérite des horaires de l'occurrence."""
    ov = (await db.execute(
        select(Event).where(and_(Event.recurrence_parent_id == maitre.id,
                                 Event.recurrence_date == occurrence))
    )).scalar_one_or_none()
    duree = maitre.end_at - maitre.start_at
    if ov is None:
        ov = Event(calendar_id=maitre.calendar_id, created_by=maitre.created_by,
                   title=maitre.title, description=maitre.description,
                   location=maitre.location, color=maitre.color, label_id=maitre.label_id,
                   all_day=maitre.all_day, rappels=list(maitre.rappels or []),
                   start_at=occurrence, end_at=occurrence + duree,
                   recurrence_parent_id=maitre.id, recurrence_date=occurrence)
        db.add(ov)
    for k, v in champs.items():
        setattr(ov, k, v)
    await db.commit()
    await db.refresh(ov)
    return ov
