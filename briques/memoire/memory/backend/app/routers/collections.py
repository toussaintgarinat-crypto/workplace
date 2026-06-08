from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.collection import Collection, CollectionNode
from app.models.node import Node, NodeStatus, NodeType, IpCraStage, StorageTier
from app.schemas.collection import CollectionCreate, CollectionUpdate, CollectionResponse
from app.schemas.search import SearchResult
from app.llm.embedder import Embedder

router = APIRouter()


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    space_id: UUID,
    req: CollectionCreate,
    db: AsyncSession = Depends(get_db),
):
    collection = Collection(
        space_id=space_id,
        name=req.name,
        description=req.description,
        filter_criteria=req.filter_criteria,
        is_dynamic=req.is_dynamic,
    )
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    return CollectionResponse(
        id=collection.id,
        space_id=collection.space_id,
        name=collection.name,
        description=collection.description,
        filter_criteria=collection.filter_criteria,
        is_dynamic=collection.is_dynamic,
        node_count=0,
        created_at=collection.created_at,
    )


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Collection).where(Collection.space_id == space_id).order_by(Collection.name)
    )
    collections = result.scalars().all()
    responses = []
    for c in collections:
        count = await db.execute(
            select(func.count(CollectionNode.id)).where(CollectionNode.collection_id == c.id)
        )
        node_count = count.scalar() or 0
        responses.append(CollectionResponse(
            id=c.id,
            space_id=c.space_id,
            name=c.name,
            description=c.description or "",
            filter_criteria=c.filter_criteria,
            is_dynamic=c.is_dynamic,
            node_count=node_count,
            created_at=c.created_at,
        ))
    return responses


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    space_id: UUID,
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id, Collection.space_id == space_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")
    count = await db.execute(
        select(func.count(CollectionNode.id)).where(CollectionNode.collection_id == c.id)
    )
    return CollectionResponse(
        id=c.id,
        space_id=c.space_id,
        name=c.name,
        description=c.description or "",
        filter_criteria=c.filter_criteria,
        is_dynamic=c.is_dynamic,
        node_count=count.scalar() or 0,
        created_at=c.created_at,
    )


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    space_id: UUID,
    collection_id: UUID,
    req: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id, Collection.space_id == space_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")
    if req.name is not None:
        c.name = req.name
    if req.description is not None:
        c.description = req.description
    if req.filter_criteria is not None:
        c.filter_criteria = req.filter_criteria
    await db.commit()
    await db.refresh(c)
    count = await db.execute(
        select(func.count(CollectionNode.id)).where(CollectionNode.collection_id == c.id)
    )
    return CollectionResponse(
        id=c.id,
        space_id=c.space_id,
        name=c.name,
        description=c.description or "",
        filter_criteria=c.filter_criteria,
        is_dynamic=c.is_dynamic,
        node_count=count.scalar() or 0,
        created_at=c.created_at,
    )


@router.delete("/{collection_id}")
async def delete_collection(
    space_id: UUID,
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id, Collection.space_id == space_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")
    await db.delete(c)
    await db.commit()
    return {"detail": "Collection deleted"}


@router.post("/{collection_id}/nodes/{node_id}")
async def add_node_to_collection(
    space_id: UUID,
    collection_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    col_result = await db.execute(
        select(Collection).where(Collection.id == collection_id, Collection.space_id == space_id)
    )
    c = col_result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")

    node_result = await db.execute(
        select(Node).where(Node.id == node_id, Node.space_id == space_id)
    )
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    existing = await db.execute(
        select(CollectionNode).where(
            CollectionNode.collection_id == collection_id,
            CollectionNode.node_id == node_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"detail": "Node already in collection"}

    cn = CollectionNode(collection_id=collection_id, node_id=node_id)
    db.add(cn)
    await db.commit()
    return {"detail": "Node added to collection"}


@router.delete("/{collection_id}/nodes/{node_id}")
async def remove_node_from_collection(
    space_id: UUID,
    collection_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CollectionNode).where(
            CollectionNode.collection_id == collection_id,
            CollectionNode.node_id == node_id,
        )
    )
    cn = result.scalar_one_or_none()
    if not cn:
        raise HTTPException(status_code=404, detail="Node not in collection")
    await db.delete(cn)
    await db.commit()
    return {"detail": "Node removed from collection"}


@router.get("/{collection_id}/nodes", response_model=list[dict])
async def list_collection_nodes(
    space_id: UUID,
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id, Collection.space_id == space_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")

    if c.is_dynamic and c.filter_criteria:
        query = select(Node).where(Node.space_id == space_id, Node.status.in_([NodeStatus.active, NodeStatus.archived]))
        for key, value in (c.filter_criteria or {}).items():
            if key == "type":
                query = query.where(Node.type == NodeType(value))
            elif key == "stage":
                query = query.where(Node.ipcra_stage == IpCraStage(value))
            elif key == "tier":
                query = query.where(Node.storage_tier == StorageTier(value))
            elif key == "resource_type":
                from sqlalchemy.dialects.postgresql import JSONB
                query = query.where(Node.frontmatter["resource_type"].astext == value)
        query = query.order_by(Node.updated_at.desc()).limit(100)
        node_result = await db.execute(query)
        nodes = node_result.scalars().all()
        return [
            {"id": str(n.id), "title": n.title, "type": n.type.value if n.type else "", "storage_tier": n.storage_tier.value if n.storage_tier else "hot"}
            for n in nodes
        ]

    cn_result = await db.execute(
        select(Node).join(CollectionNode, CollectionNode.node_id == Node.id).where(
            CollectionNode.collection_id == collection_id,
            Node.space_id == space_id,
        ).order_by(CollectionNode.added_at.desc())
    )
    nodes = cn_result.scalars().all()
    return [
        {"id": str(n.id), "title": n.title, "type": n.type.value if n.type else "", "storage_tier": n.storage_tier.value if n.storage_tier else "hot"}
        for n in nodes
    ]


@router.get("/{collection_id}/search", response_model=list[SearchResult])
async def search_collection(
    space_id: UUID,
    collection_id: UUID,
    q: str = Query(""),
    limit: int = Query(20),
    db: AsyncSession = Depends(get_db),
):
    if not q.strip():
        return []

    result = await db.execute(
        select(Collection).where(Collection.id == collection_id, Collection.space_id == space_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")

    embedder = Embedder()
    query_embedding = await embedder.embed_text(q)
    if not query_embedding:
        return []

    embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    if c.is_dynamic and c.filter_criteria:
        conditions = ["n.space_id = :space_id", "n.embedding IS NOT NULL"]
        params = {"space_id": space_id, "limit": limit, "embedding": embedding_literal}
        for key, value in (c.filter_criteria or {}).items():
            if key == "type":
                conditions.append("n.type = :filter_type")
                params["filter_type"] = value
            elif key == "stage":
                conditions.append("n.ipcra_stage = :filter_stage")
                params["filter_stage"] = value
            elif key == "tier":
                conditions.append("n.storage_tier = :filter_tier")
                params["filter_tier"] = value
            elif key == "resource_type":
                conditions.append("n.frontmatter->>'resource_type' = :filter_rt")
                params["filter_rt"] = value
        where = " AND ".join(conditions)
    else:
        conditions = [
            "n.space_id = :space_id",
            "n.embedding IS NOT NULL",
            "n.id IN (SELECT cn.node_id FROM collection_nodes cn WHERE cn.collection_id = :collection_id)",
        ]
        params = {"space_id": space_id, "collection_id": collection_id, "limit": limit, "embedding": embedding_literal}
        where = " AND ".join(conditions)

    search_words = q.strip().split()
    text_rank = ""
    if search_words:
        word_conds = " OR ".join(
            f"(n.title ILIKE :w{i} OR n.content_md ILIKE :w{i})"
            for i in range(len(search_words))
        )
        for i, w in enumerate(search_words):
            params[f"w{i}"] = f"%{w}%"
        text_rank = f"+ CASE WHEN ({word_conds}) THEN 0.3 ELSE 0 END"

    sql = text(f"""
        SELECT n.id, n.title, n.content_md, n.type, n.storage_tier, n.happened_at,
               (1 - (n.embedding <=> :embedding::vector)) {text_rank} AS score
        FROM nodes n
        WHERE {where}
        ORDER BY score DESC
        LIMIT :limit
    """)

    rows_result = await db.execute(sql, params)
    rows = rows_result.all()

    return [
        SearchResult(
            id=row[0],
            title=row[1],
            content_md=(row[2] or "")[:300],
            type=row[3].value if hasattr(row[3], 'value') else row[3],
            storage_tier=row[4].value if hasattr(row[4], 'value') else (row[4] or "hot"),
            happened_at=row[5],
            score=float(row[6]) if row[6] else 0.0,
        )
        for row in rows
    ]
