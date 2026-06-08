from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.template import Template as TemplateModel

router = APIRouter()


class TemplateSchema(BaseModel):
    id: UUID
    name: str
    node_type: str
    title_template: str
    content_template: str
    frontmatter_template: Optional[str] = None
    is_global: bool

    model_config = {"from_attributes": True}


class TemplateCreate(BaseModel):
    name: str
    node_type: str
    title_template: str = ""
    content_template: str = ""
    frontmatter_template: Optional[str] = None


DEFAULT_TEMPLATES = [
    {
        "name": "Quick Capture",
        "node_type": "input",
        "title_template": "New Input",
        "content_template": "## Summary\n\n## Details\n\n## Questions\n",
        "frontmatter_template": '{"priority": "medium"}',
    },
    {
        "name": "Project",
        "node_type": "projet",
        "title_template": "New Project",
        "content_template": "## Objective\n\n## Context\n\n## Next Actions\n\n## Notes\n",
        "frontmatter_template": '{"status": "active", "priority": "medium", "next_actions": []}',
    },
    {
        "name": "Role",
        "node_type": "casquette",
        "title_template": "New Role",
        "content_template": "## Responsibilities\n\n## Domains\n\n## Related Projects\n",
        "frontmatter_template": '{"responsabilites": [], "domaines": []}',
    },
    {
        "name": "Resource",
        "node_type": "ressource",
        "title_template": "New Resource",
        "content_template": "## Description\n\n## Usage Notes\n\n## Related Resources\n",
        "frontmatter_template": '{"resource_type": "article", "tags": []}',
    },
    {
        "name": "Archive",
        "node_type": "archive",
        "title_template": "Archived",
        "content_template": "## Context\n\n## Result\n\n## Lessons Learned\n",
        "frontmatter_template": '{"lessons_learned": ""}',
    },
]


@router.get("")
async def list_templates(
    space_id: UUID,
    node_type: str = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(TemplateModel).where(
        (TemplateModel.space_id == space_id) | (TemplateModel.is_global == "true")
    )
    if node_type:
        query = query.where(TemplateModel.node_type == node_type)
    query = query.order_by(TemplateModel.name)
    result = await db.execute(query)
    db_templates = result.scalars().all()

    seen = {t.name for t in db_templates if t.space_id == space_id or t.is_global == "true"}

    all_templates = [
        TemplateSchema(
            id=t.id,
            name=t.name,
            node_type=t.node_type,
            title_template=t.title_template,
            content_template=t.content_template,
            frontmatter_template=t.frontmatter_template,
            is_global=t.is_global == "true",
        )
        for t in db_templates
    ]

    defaults = [d for d in DEFAULT_TEMPLATES if d["name"] not in seen]
    for dt in defaults:
        if node_type and dt["node_type"] != node_type:
            continue
        all_templates.append(TemplateSchema(
            id=UUID(int=0),
            name=dt["name"],
            node_type=dt["node_type"],
            title_template=dt["title_template"],
            content_template=dt["content_template"],
            frontmatter_template=dt["frontmatter_template"],
            is_global=True,
        ))

    return all_templates


@router.post("", status_code=201)
async def create_template(
    space_id: UUID,
    req: TemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    tmpl = TemplateModel(
        space_id=space_id,
        name=req.name,
        node_type=req.node_type,
        title_template=req.title_template,
        content_template=req.content_template,
        frontmatter_template=req.frontmatter_template,
        is_global="false",
    )
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return TemplateSchema(
        id=tmpl.id,
        name=tmpl.name,
        node_type=tmpl.node_type,
        title_template=tmpl.title_template,
        content_template=tmpl.content_template,
        frontmatter_template=tmpl.frontmatter_template,
        is_global=False,
    )


@router.delete("/{template_id}")
async def delete_template(
    space_id: UUID,
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TemplateModel).where(
            TemplateModel.id == template_id,
            TemplateModel.space_id == space_id,
        )
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tmpl)
    await db.commit()
    return {"detail": "Template deleted"}
