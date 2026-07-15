"""Journal d'activité d'un événement (S174) : écrit une entrée en capturant le nom
affichable de l'auteur au moment de l'action (snapshot robuste). Ne commite pas."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import EventActivityLog
from services import profils


async def consigner(db: AsyncSession, event_id: str, user_id: str, action: str,
                    details: dict | None = None) -> None:
    """Ajoute une entrée de journal (nom snapshoté). Actions : event_created,
    event_updated, event_deleted, rsvp, comment. L'appelant commite.

    created_at est posé explicitement (microseconde) plutôt que laissé au
    server_default : CURRENT_TIMESTAMP (SQLite) n'a qu'une résolution de la
    seconde, ce qui rend l'ordre de deux entrées consignées dans la même
    seconde ambigu (cas courant : create_event + son propre event_created,
    ou deux actions rapprochées). L'horodatage Python garantit l'ordre.
    """
    resolus = await profils.resoudre(db, [user_id])
    nom = resolus[user_id]["display_name"]
    db.add(EventActivityLog(event_id=event_id, user_id=user_id, user_nom=nom,
                            action=action, details=details,
                            created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
