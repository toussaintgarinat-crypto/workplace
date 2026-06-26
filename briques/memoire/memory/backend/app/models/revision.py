import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class NodeRevision(Base):
    """Instantané de l'état d'un nœud AVANT une édition (historique opt-in, S110).

    Une révision n'est conservée que si le nœud a `track_history` activé. Chaque
    ligne fige (title, content_md, frontmatter) tels qu'ils étaient juste avant que
    l'édition ne les remplace → on peut relire ou restaurer une version passée, et
    plus tard (S111) faire glisser un curseur de date sur le graphe.

    `captured_at` = instant où la version a été supplantée (= date de l'édition qui
    l'archive). La suppression d'un nœud emporte ses révisions (FK CASCADE).
    """

    __tablename__ = "node_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    content_md = Column(Text, default="")
    frontmatter = Column(JSONB, default=dict)
    captured_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_node_revisions_node", "node_id", "captured_at"),
        Index("idx_node_revisions_space", "space_id"),
    )
