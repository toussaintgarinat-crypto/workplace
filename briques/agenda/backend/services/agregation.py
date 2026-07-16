"""Orchestration de haut niveau pour la surface `/service` (S168).

Rapatrie DANS la brique la logique qui vivait côté Cœur (`core/agenda.py`) : agrégation
multi-calendriers + jointure étiquettes/couleur, et résolution du calendrier par défaut.
Le dispatcher générique du Cœur (`_appel_dynamique`) ne sait pas exprimer cette
orchestration ; c'est pourquoi elle devient une capacité de service ici, pas un passe-plat.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, CalendarMember, EventParticipant, Label
from services.occurrences import occurrence_en_dict, occurrences_calendrier
from services.rappels import rappels_effectifs


async def calendriers_accessibles(db: AsyncSession, user_id: str) -> list[Calendar]:
    """Calendriers possédés + partagés (membre), dédoublonnés. Même périmètre que
    `GET /calendars` — la source de vérité de ce qu'un utilisateur peut voir."""
    owned = (await db.execute(
        select(Calendar).where(Calendar.user_id == user_id)
    )).scalars().all()
    ids = {c.id for c in owned}
    partages = (await db.execute(
        select(Calendar).join(CalendarMember, CalendarMember.calendar_id == Calendar.id)
        .where(CalendarMember.user_id == user_id)
    )).scalars().all()
    return list(owned) + [c for c in partages if c.id not in ids]


async def evenements_agreges(db: AsyncSession, user_id: str,
                             debut: datetime | None, fin: datetime | None) -> list[dict]:
    """Occurrences (maîtres + récurrences dépliées + overrides) de TOUS les calendriers
    accessibles sur [debut, fin], enrichies de `calendrier` (nom), `etiquette` (nom) et
    `couleur` (étiquette > event > calendrier).

    Miroir fidèle de l'ancien `core/agenda.lister_evenements`, augmenté S175 de l'expansion
    de récurrence (`services.occurrences`) : sans l'agrégation, les événements rapatriés
    (Google, TimeTree — qui vivent dans un calendrier dédié) seraient invisibles au
    dashboard ET au briefing proactif ; sans l'expansion, une série récurrente n'apparaîtrait
    qu'une fois (son maître)."""
    cals = await calendriers_accessibles(db, user_id)
    evts: list[dict] = []
    for c in cals:
        # Étiquettes du calendrier {id: Label} pour résoudre nom + couleur.
        labels = {l.id: l for l in (await db.execute(
            select(Label).where(Label.calendar_id == c.id)
        )).scalars().all()}
        occ = await occurrences_calendrier(db, c.id, debut, fin)
        # Participants chargés EN LOT pour tous les events sources (maîtres + overrides) de
        # ce calendrier — évite le N+1 qu'aggraverait l'expansion (une requête par occurrence).
        src_ids = {o.source.id for o in occ}
        parts_par_event: dict[str, list] = {}
        if src_ids:
            for p in (await db.execute(
                select(EventParticipant).where(EventParticipant.event_id.in_(src_ids))
            )).scalars().all():
                parts_par_event.setdefault(p.event_id, []).append(p)
        for o in occ:
            e = o.source
            d = occurrence_en_dict(o)
            lab = labels.get(e.label_id)
            d["calendrier"] = c.name
            d["etiquette"] = lab.name if lab else None
            d["couleur"] = (lab.color if lab else None) or e.color or c.color
            d["participants"] = [
                {"user_id": p.user_id, "status": p.status,
                 "rappels_effectifs": rappels_effectifs(p.rappels, e.rappels)}
                for p in parts_par_event.get(e.id, [])
            ]
            evts.append(d)
    return evts


async def calendrier_defaut(db: AsyncSession, user_id: str) -> Calendar:
    """Calendrier d'écriture par défaut de l'utilisateur : le marqué `is_default`, sinon le
    premier possédé, sinon un « Perso » créé à la volée (la brique n'en crée pas seule)."""
    owned = (await db.execute(
        select(Calendar).where(Calendar.user_id == user_id).order_by(Calendar.created_at)
    )).scalars().all()
    if owned:
        return next((c for c in owned if c.is_default), owned[0])
    cal = Calendar(user_id=user_id, name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal
