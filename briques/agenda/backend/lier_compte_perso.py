"""Script one-off (S172) : relie le compte Keycloak réel de l'utilisateur principal aux
calendriers actuellement épinglés "perso" (posé par le dialecte S2S de l'assistant,
cf. `config.AGENDA_USER_ID`). Sans ce pont, un vrai compte `calendar-app` ne serait
reconnu propriétaire d'aucun calendrier existant (`utils.access.get_user_role` compare
`Calendar.user_id == user_id`).

Lancé une seule fois à la main, jamais exposé en route HTTP (cf. design S172 :
docs/superpowers/specs/2026-07-15-s172-agenda-application-autonome-design.md).

Usage :
  cd briques/agenda/backend && python3 lier_compte_perso.py <sub-keycloak>

Le <sub-keycloak> s'obtient après une première connexion à /app : décoder le payload du
access_token (ex. jwt.io), champ "sub".
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, CalendarMember


async def lier_compte_perso(sub: str, db: AsyncSession) -> list[str]:
    """Ajoute CalendarMember(role="owner") pour `sub` sur chaque calendrier "perso" qui
    n'a pas déjà de ligne pour ce sub. Idempotent (relançable sans dupliquer). Retourne
    les ids des calendriers nouvellement liés."""
    cals = (await db.execute(select(Calendar).where(Calendar.user_id == "perso"))).scalars().all()
    lies: list[str] = []
    for cal in cals:
        existant = (await db.execute(
            select(CalendarMember).where(
                CalendarMember.calendar_id == cal.id,
                CalendarMember.user_id == sub,
            )
        )).scalar_one_or_none()
        if existant:
            continue
        db.add(CalendarMember(calendar_id=cal.id, user_id=sub, role="owner"))
        lies.append(cal.id)
    await db.commit()
    return lies


async def _main(sub: str) -> None:
    from db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        lies = await lier_compte_perso(sub, db)
    print(f"{len(lies)} calendrier(s) lié(s) : {lies}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 lier_compte_perso.py <sub-keycloak>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
