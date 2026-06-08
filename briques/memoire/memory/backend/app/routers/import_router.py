from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.dependencies import check_space_access
from app.services.node_service import NodeService

router = APIRouter()


class ImportNode(BaseModel):
    title: str
    content_md: str = ""
    type: str = "input"
    frontmatter: dict = {}
    source_url: str = ""
    captured_from: str = ""
    happened_at: Optional[datetime] = None


class ImportRequest(BaseModel):
    nodes: list[ImportNode]
    format: str = "json"


class ImportResponse(BaseModel):
    imported: int
    errors: int


@router.post("", response_model=ImportResponse)
async def import_space(
    space_id: UUID,
    req: ImportRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_space_access),
):
    svc = NodeService(db)
    imported = 0
    errors = 0

    for node_data in req.nodes:
        try:
            await svc.create_node(
                space_id=space_id,
                type=node_data.type,
                title=node_data.title,
                content_md=node_data.content_md,
                frontmatter=node_data.frontmatter or {},
                source_url=node_data.source_url or None,
                captured_from=node_data.captured_from or None,
                happened_at=node_data.happened_at,
            )
            imported += 1
        except Exception:
            errors += 1

    return ImportResponse(imported=imported, errors=errors)
