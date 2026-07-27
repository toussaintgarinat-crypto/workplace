from fastapi import APIRouter
from sqlalchemy import text

from db import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/sante")
async def health():
    """Santé de la brique, servie sur DEUX chemins (S207).

    `/sante` est la convention du parc ; `/health` est conservé car le healthcheck Docker et
    le manifest pointent dessus — retirer l'ancien chemin casserait le conteneur.
    """
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "db": db_ok}
