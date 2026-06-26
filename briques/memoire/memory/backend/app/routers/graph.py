from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.schemas.graph import EdgeCreate, GraphResponse, GraphNode, NodePosition
from app.services.graph_service import GraphService

router = APIRouter()


@router.get("", response_model=GraphResponse)
async def get_graph(
    space_id: UUID,
    depth: int = Query(2),
    root: UUID = Query(None),
    db: AsyncSession = Depends(get_db),
):
    svc = GraphService(db)
    return await svc.get_subgraph(space_id, root=root, depth=depth)


@router.post("/edges")
async def create_edge(space_id: UUID, req: EdgeCreate, db: AsyncSession = Depends(get_db)):
    svc = GraphService(db)
    edge = await svc.create_edge(space_id, req.source_id, req.target_id, req.type, req.weight)
    if not edge:
        raise HTTPException(status_code=400, detail="Could not create edge")
    return {"id": str(edge.id), "source_id": str(edge.source_id), "target_id": str(edge.target_id), "type": edge.type.value}


@router.delete("/edges/{edge_id}")
async def delete_edge(space_id: UUID, edge_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GraphService(db)
    success = await svc.delete_edge(edge_id)
    if not success:
        raise HTTPException(status_code=404, detail="Edge not found")
    return {"detail": "Edge deleted"}


@router.put("/nodes/{node_id}/position", response_model=GraphNode)
async def set_node_position(
    space_id: UUID,
    node_id: UUID,
    pos: NodePosition,
    db: AsyncSession = Depends(get_db),
):
    """Persiste la position d'un nœud déplacé sur le canvas (S109)."""
    svc = GraphService(db)
    node = await svc.set_node_position(space_id, node_id, pos.x, pos.y)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return GraphNode(id=node.id, title=node.title, type=node.type.value, pos=pos)


@router.get("/path", response_model=list[GraphNode])
async def find_path(
    space_id: UUID,
    source: UUID = Query(...),
    target: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    svc = GraphService(db)
    path = await svc.find_shortest_path(space_id, source, target)
    return path
