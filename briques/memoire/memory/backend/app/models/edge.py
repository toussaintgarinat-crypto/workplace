import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Float, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

import enum


class EdgeType(str, enum.Enum):
    cause = "cause"
    related = "related"
    part_of = "part_of"
    references = "references"
    contradicts = "contradicts"
    derived_from = "derived_from"
    custom = "custom"


class EdgeCreator(str, enum.Enum):
    user = "user"
    llm = "llm"
    auto = "auto"


class Edge(Base):
    __tablename__ = "edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    type = Column(Enum(EdgeType), nullable=False, default=EdgeType.related)
    weight = Column(Float, default=1.0)
    edge_metadata = Column("metadata", UUID(as_uuid=True), nullable=True)
    created_by = Column(Enum(EdgeCreator), nullable=False, default=EdgeCreator.user)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # Soft-delete (S112) : si l'espace suit son histoire, supprimer un lien ne l'efface
    # pas mais l'horodate. « Lien vivant à T » = created_at ≤ T < deleted_at (ou NULL).
    # NULL = lien présent. Hors suivi, la suppression reste un hard-delete (cf. service).
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    source_node = relationship("Node", foreign_keys=[source_id], back_populates="edges_out")
    target_node = relationship("Node", foreign_keys=[target_id], back_populates="edges_in")
