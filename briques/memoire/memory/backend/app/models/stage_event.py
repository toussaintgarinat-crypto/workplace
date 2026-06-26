import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.models.node import IpCraStage


class NodeStageEvent(Base):
    """Transition de stade IPCRA d'un nœud, horodatée (journal temporel, S112).

    N'est écrit que si l'espace a `track_history` activé. Chaque ligne fige le passage
    d'un stade à un autre :
      - `from_stage = NULL` → évènement de CRÉATION (le nœud naît avec `to_stage`).
      - sinon → transition (l'utilisateur a fait passer le nœud de `from_stage` à `to_stage`).

    « Stade à T » = `to_stage` du dernier évènement dont `at ≤ T`. S'il n'en existe aucun
    (suivi activé après coup), on ne réinvente pas l'avant-activation : repli honnête sur
    le stade courant côté service. La suppression d'un nœud emporte ses évènements (CASCADE).
    """

    __tablename__ = "node_stage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    from_stage = Column(Enum(IpCraStage), nullable=True)
    to_stage = Column(Enum(IpCraStage), nullable=False)
    at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_stage_events_space_at", "space_id", "at"),
        Index("idx_stage_events_node", "node_id", "at"),
    )
