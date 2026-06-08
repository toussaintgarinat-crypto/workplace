"""RGPD exécutable (S18, Chantier 2) — effacement et export réels, scopés par sujet.

Contrairement à ``sentinel_rgpd`` (audit consultatif : checklist + commentaire LLM),
ce module **agit sur les données** :

- **Effacement** (Art. 17) : balaye *toutes* les tables portant une colonne ``user_id``
  (introspection des métadonnées SQLAlchemy → robuste aux ajouts de tables), dans un
  ordre respectant les clés étrangères, puis supprime la ligne ``users`` du sujet ;
  efface aussi les vecteurs RAG du sujet dans Qdrant ; tente l'oubli côté brique Mémoire.
- **Export** (Art. 15 & 20) : sérialise en JSON toutes les lignes du sujet.

Le périmètre est le **sujet lui-même** (self-service). Limites assumées :
- les enfants sans ``user_id`` direct (ex. ``messages`` via ``session_id``) dépendent
  d'un ``ON DELETE CASCADE`` au niveau base ;
- la brique Mémoire écrit aujourd'hui sans ``user_id`` → oubli sélectif non garanti
  (cf. ``app.memory.mem_forget_user``).
"""

from __future__ import annotations

import datetime
import uuid as uuidlib
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import memory as mem
from app.models import Base


def _as_uuid(user_id: str) -> uuidlib.UUID:
    return user_id if isinstance(user_id, uuidlib.UUID) else uuidlib.UUID(str(user_id))


def tables_with_user_id() -> list:
    """Tables (objets Core) portant une colonne ``user_id``, en ordre FK-safe
    pour la **suppression** (enfants avant parents)."""
    ordered = list(reversed(Base.metadata.sorted_tables))
    return [t for t in ordered if "user_id" in t.c]


def _users_table():
    return Base.metadata.tables.get("users")


async def erase_user_postgres(session: AsyncSession, user_id: str) -> dict[str, int]:
    """Supprime toutes les lignes du sujet dans Postgres. Renvoie {table: lignes}.

    L'ordre (enfants → parents) évite les violations de FK. La ligne ``users`` du
    sujet est supprimée en dernier.
    """
    uid = _as_uuid(user_id)
    counts: dict[str, int] = {}
    for table in tables_with_user_id():
        res = await session.execute(sa_delete(table).where(table.c.user_id == uid))
        if res.rowcount:
            counts[table.name] = res.rowcount
    users = _users_table()
    if users is not None:
        res = await session.execute(sa_delete(users).where(users.c.id == uid))
        if res.rowcount:
            counts["users"] = res.rowcount
    await session.commit()
    return counts


async def export_user_postgres(session: AsyncSession, user_id: str) -> dict[str, list[dict]]:
    """Sérialise (JSON-compatible) toutes les lignes du sujet, par table.

    Réutilise l'inventaire ``user_id`` du Chantier 1/2. Les valeurs non sérialisables
    (UUID, datetime, Decimal) sont rendues en ``str``.
    """
    uid = _as_uuid(user_id)
    out: dict[str, list[dict]] = {}
    # Ordre lisible (parents avant enfants) pour l'export.
    for table in [t for t in Base.metadata.sorted_tables if "user_id" in t.c]:
        rows = (await session.execute(select(table).where(table.c.user_id == uid))).mappings().all()
        if rows:
            out[table.name] = [_jsonable(dict(r)) for r in rows]
    users = _users_table()
    if users is not None:
        urow = (await session.execute(select(users).where(users.c.id == uid))).mappings().first()
        if urow:
            out["users"] = [_jsonable(dict(urow))]
    return out


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            clean[k] = v.isoformat()
        elif isinstance(v, uuidlib.UUID):
            clean[k] = str(v)
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            clean[k] = float(v)  # Decimal
        else:
            clean[k] = v
    return clean


async def erase_user_all_stores(session: AsyncSession, user_id: str) -> dict[str, Any]:
    """Effacement multi-store : Postgres + Qdrant + (best-effort) brique Mémoire.

    Renvoie un **reçu** détaillé (par magasin), persisté en mémoire Workplace pour
    conserver une preuve d'exécution (Art. 17(3) — registre minimal de l'effacement).
    """
    pg = await erase_user_postgres(session, user_id)
    qdrant = await mem.delete_by_user(str(user_id))
    memoire = await mem.mem_forget_user(str(user_id))
    recu = {
        "sujet": str(user_id),
        "efface_le": datetime.datetime.utcnow().isoformat() + "Z",
        "postgres": pg,
        "postgres_total_lignes": sum(pg.values()),
        "qdrant": qdrant,
        "memoire": memoire,
    }
    # Reçu d'effacement conservé hors périmètre sujet (preuve d'exécution).
    await mem.mem_retenir(
        f"Effacement RGPD du sujet {user_id} : {recu['postgres_total_lignes']} lignes Postgres, "
        f"vecteurs Qdrant {qdrant}.",
        titre=f"RGPD effacement {user_id}",
        type_="rgpd_effacement",
    )
    return recu
