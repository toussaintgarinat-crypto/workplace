from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node
from app.llm.embedder import Embedder


class EmbedService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = Embedder()

    async def embed_node(self, node_id: UUID) -> Optional[list[float]]:
        result = await self.db.execute(select(Node).where(Node.id == node_id))
        node = result.scalar_one_or_none()
        if not node or not node.content_md:
            return None

        text = f"{node.title}\n{node.content_md}"
        embedding = await self.embedder.embed_text(text)
        if embedding:
            node.embedding = embedding
            await self.db.commit()
        return embedding

    async def embed_all_missing(self, space_id: UUID) -> int:
        result = await self.db.execute(
            select(Node).where(Node.space_id == space_id, Node.embedding.is_(None))
        )
        nodes = result.scalars().all()
        for node in nodes:
            text = f"{node.title}\n{node.content_md}"
            embedding = await self.embedder.embed_text(text)
            if embedding:
                node.embedding = embedding
        await self.db.commit()
        return len(nodes)
