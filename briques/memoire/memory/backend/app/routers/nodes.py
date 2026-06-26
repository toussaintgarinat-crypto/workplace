from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.models.node import Node
from app.schemas.node import NodeCreate, NodeUpdate, NodeResponse, NodeStageUpdate, NodeLocationUpdate, EdgeRef, NodeRevisionResponse
from app.services.node_service import NodeService

router = APIRouter()


def node_to_response(node: Node) -> NodeResponse:
    edges = []
    for e in getattr(node, "edges_out", []) or []:
        edges.append(EdgeRef(id=e.id, source_id=e.source_id, target_id=e.target_id, type=e.type.value, weight=e.weight))
    for e in getattr(node, "edges_in", []) or []:
        edges.append(EdgeRef(id=e.id, source_id=e.source_id, target_id=e.target_id, type=e.type.value, weight=e.weight))
    return NodeResponse(
        id=node.id,
        space_id=node.space_id,
        type=node.type.value if node.type else "",
        ipcra_stage=node.ipcra_stage.value if node.ipcra_stage else "",
        storage_tier=node.storage_tier.value if node.storage_tier else "hot",
        status=node.status.value if node.status else "",
        title=node.title,
        content_md=node.content_md or "",
        frontmatter=node.frontmatter or {},
        access_count=node.access_count,
        last_accessed=node.last_accessed,
        happened_at=node.happened_at,
        stage_changed_at=node.stage_changed_at,
        source_url=node.source_url,
        captured_from=node.captured_from,
        location=None,
        edges=edges,
        track_history=bool(getattr(node, "track_history", False)),
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    space_id: UUID,
    type: str = Query(None),
    stage: str = Query(None),
    tier: str = Query(None),
    status: str = Query("active"),
    wing: str = Query(None),
    room: str = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    svc = NodeService(db)
    nodes = await svc.list_nodes(space_id, type=type, stage=stage, tier=tier, status=status, wing=wing, room=room, limit=limit, offset=offset)
    return [node_to_response(n) for n in nodes]


@router.post("", response_model=NodeResponse, status_code=201)
async def create_node(space_id: UUID, req: NodeCreate, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    node = await svc.create_node(
        space_id=space_id,
        type=req.type,
        title=req.title,
        content_md=req.content_md,
        frontmatter=req.frontmatter,
        source_url=req.source_url,
        captured_from=req.captured_from,
        happened_at=req.happened_at,
        location=req.location,
    )
    return node_to_response(node)


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(space_id: UUID, node_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    node = await svc.get_node(node_id, space_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node_to_response(node)


@router.put("/{node_id}", response_model=NodeResponse)
async def update_node(space_id: UUID, node_id: UUID, req: NodeUpdate, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    node = await svc.update_node(node_id, space_id, req.model_dump(exclude_unset=True))
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node_to_response(node)


@router.patch("/{node_id}/stage", response_model=NodeResponse)
async def update_node_stage(space_id: UUID, node_id: UUID, req: NodeStageUpdate, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    node = await svc.update_stage(node_id, space_id, req.stage)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node_to_response(node)


@router.put("/{node_id}/location", response_model=NodeResponse)
async def update_node_location(space_id: UUID, node_id: UUID, req: NodeLocationUpdate, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    node = await svc.update_location(node_id, space_id, req.wing, req.room, req.drawer)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node_to_response(node)


@router.get("/{node_id}/revisions", response_model=list[NodeRevisionResponse])
async def list_node_revisions(
    space_id: UUID, node_id: UUID, limit: int = Query(50), db: AsyncSession = Depends(get_db)
):
    """Historique des versions d'un nœud (opt-in via `track_history`), récentes d'abord."""
    svc = NodeService(db)
    revisions = await svc.list_revisions(node_id, space_id, limit=limit)
    if revisions is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return revisions


@router.get("/{node_id}/revisions/{revision_id}", response_model=NodeRevisionResponse)
async def get_node_revision(
    space_id: UUID, node_id: UUID, revision_id: UUID, db: AsyncSession = Depends(get_db)
):
    svc = NodeService(db)
    revision = await svc.get_revision(node_id, space_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


@router.post("/{node_id}/revisions/{revision_id}/restore", response_model=NodeResponse)
async def restore_node_revision(
    space_id: UUID, node_id: UUID, revision_id: UUID, db: AsyncSession = Depends(get_db)
):
    """Restaure une version passée (l'état courant est lui-même archivé au passage)."""
    svc = NodeService(db)
    node = await svc.restore_revision(node_id, space_id, revision_id)
    if not node:
        raise HTTPException(status_code=404, detail="Revision not found")
    return node_to_response(node)


@router.delete("/{node_id}")
async def delete_node(space_id: UUID, node_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    success = await svc.soft_delete(node_id, space_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"detail": "Node archived"}
