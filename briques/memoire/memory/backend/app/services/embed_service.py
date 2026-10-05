import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select, text
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
        """Vectorise jusqu'à `limite` souvenirs sans vecteur (tous espaces). Si l'embedder
        échoue sur un souvenir, une sonde (texte anodin) départage : sonde en échec = vraie
        panne, on s'arrête ; sonde réussie = ce souvenir seul pose problème, on le saute.
        Chaque vecteur est écrit par un UPDATE conditionnel (toujours sans vecteur et
        `updated_at` inchangé) : une modification concurrente n'est jamais écrasée."""
        result = await self.db.execute(
            select(Node.id, Node.title, Node.content_md, Node.updated_at)
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
        candidats = result.all()
        await self.db.rollback()  # ne garde aucune transaction ouverte pendant les appels réseau
        faits = 0
        for node_id, titre, contenu, vu in candidats:
            try:
                embedding = await self.embedder.embed_text(f"{titre}\n{contenu or ''}")
            except EmbeddingIndisponible as exc:
                try:
                    await self.embedder.embed_text("sonde")
                except EmbeddingIndisponible:
                    journal.warning("Revectorisation interrompue (embedder indisponible) : %s", exc)
                    break
                journal.warning("Souvenir %s ignoré (embedding impossible, embedder disponible) : %s", node_id, exc)
                continue
            if embedding is None:
                continue
            res = await self.db.execute(
                text(
                    "UPDATE nodes SET embedding = CAST(:e AS vector) "
                    "WHERE id = :id AND embedding IS NULL AND updated_at = :vu"
                ),
                {"e": "[" + ",".join(repr(float(x)) for x in embedding) + "]", "id": node_id, "vu": vu},
            )
            await self.db.commit()
            if res.rowcount == 1:
                faits += 1
        return faits
