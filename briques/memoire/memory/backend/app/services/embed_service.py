import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embedder import Embedder, EmbeddingIndisponible
from app.models.node import Node, NodeStatus

journal = logging.getLogger(__name__)


def _texte(node: Node) -> str:
    return f"{node.title}\n{node.content_md or ''}"


class EmbedService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = Embedder()

    async def embed_node(self, node_id: UUID) -> Optional[list[float]]:
        """Vectorise un souvenir. Embedder en panne : le vecteur est remis à NULL (il
        décrirait l'ancien contenu) et la tâche `revectoriser_manquants` le recalculera ;
        l'écriture du souvenir, elle, n'échoue jamais pour autant."""
        result = await self.db.execute(select(Node).where(Node.id == node_id))
        node = result.scalar_one_or_none()
        if not node:
            return None
        try:
            embedding = await self.embedder.embed_text(_texte(node))
        except EmbeddingIndisponible as exc:
            journal.warning("Embedding différé pour le souvenir %s : %s", node_id, exc)
            embedding = None
        node.embedding = embedding
        await self.db.commit()
        return embedding

    async def revectoriser_manquants(self, limite: int = 50) -> int:
        """Vectorise jusqu'à `limite` souvenirs sans vecteur (tous espaces). S'arrête au
        premier échec de l'embedder : inutile d'insister pendant une panne."""
        result = await self.db.execute(
            select(Node)
            .where(
                Node.embedding.is_(None),
                Node.status.in_([NodeStatus.active, NodeStatus.archived]),
                or_(
                    func.length(func.trim(Node.title)) > 0,
                    func.length(func.trim(func.coalesce(Node.content_md, ""))) > 0,
                ),
            )
            .order_by(Node.updated_at.desc())
            .limit(limite)
        )
        faits = 0
        for node in result.scalars().all():
            try:
                embedding = await self.embedder.embed_text(_texte(node))
            except EmbeddingIndisponible as exc:
                journal.warning("Revectorisation interrompue (embedder indisponible) : %s", exc)
                break
            if embedding is not None:
                node.embedding = embedding
                faits += 1
        await self.db.commit()
        return faits
