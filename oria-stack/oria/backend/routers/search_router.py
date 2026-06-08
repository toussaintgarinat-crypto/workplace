"""
Recherche plein-texte globale.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from routers.auth import get_current_user

router = APIRouter()


@router.get("/")
def rechercher(
    q: str = Query(..., min_length=2),
    world_id: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return {"query": q, "total": 0, "results": {}}
