"""Branche vectorielle de la recherche Mémoire (S238) : seulement si la requête a un vecteur."""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recherche_conditions import Filtres, conditions_sql

# Sous ce cosinus, un souvenir n'est pas « proche » : sans plancher, la branche renverrait
# toujours ses N plus proches voisins, même sans rapport, et la fusion les remonterait.
SIMILARITE_MINIMALE = 0.25


async def classement_vectoriel(db: AsyncSession, vecteur: list[float], filtres: Filtres, limite: int) -> list[UUID]:
    where, params = conditions_sql(filtres)
    params.update(
        embedding="[" + ",".join(str(v) for v in vecteur) + "]",
        distance_max=1 - SIMILARITE_MINIMALE,
        limite=limite,
    )
    sql = text(f"""
        SELECT n.id FROM nodes n
        WHERE {where} AND n.embedding IS NOT NULL
          AND (n.embedding <=> CAST(:embedding AS vector)) <= :distance_max
        ORDER BY n.embedding <=> CAST(:embedding AS vector), n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]
