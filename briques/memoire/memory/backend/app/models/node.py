import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, DateTime, Enum, ForeignKey, Index, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.database import Base

import enum


class NodeType(str, enum.Enum):
    input = "input"
    projet = "projet"
    casquette = "casquette"
    ressource = "ressource"
    archive = "archive"


class IpCraStage(str, enum.Enum):
    input = "input"
    projet = "projet"
    casquette = "casquette"
    ressource = "ressource"
    archive = "archive"


class StorageTier(str, enum.Enum):
    hot = "hot"
    archive = "archive"
    cold_archive = "cold_archive"


class NodeStatus(str, enum.Enum):
    active = "active"
    archived = "archived"
    pending_removal = "pending_removal"


class Node(Base):
    __tablename__ = "nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(Enum(NodeType), nullable=False)
    ipcra_stage = Column(Enum(IpCraStage), nullable=False)
    storage_tier = Column(Enum(StorageTier), nullable=False, default=StorageTier.hot)
    status = Column(Enum(NodeStatus), nullable=False, default=NodeStatus.active)
    title = Column(Text, nullable=False)
    content_md = Column(Text, default="")
    frontmatter = Column(JSONB, default=dict)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime(timezone=True), nullable=True)
    happened_at = Column(DateTime(timezone=True), nullable=True)
    stage_changed_at = Column(DateTime(timezone=True), nullable=True)
    source_url = Column(Text, nullable=True)
    captured_from = Column(Text, nullable=True)
    # Position libre du nœud sur le canvas graphe (S109) : {"x": float, "y": float}.
    # NULL = jamais déplacé → le front retombe sur une disposition en grille.
    canvas_pos = Column(JSONB, nullable=True)
    # Historique opt-in (S110) : si vrai, chaque édition archive l'état précédent
    # dans node_revisions. Faux par défaut (souveraineté + on ne gonfle pas la DB).
    track_history = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    embedding = Column(Vector(384), nullable=True)

    space = relationship("Space", back_populates="nodes")
    user = relationship("User", back_populates="nodes")
    edges_out = relationship("Edge", foreign_keys="Edge.source_id", back_populates="source_node", lazy="selectin")
    edges_in = relationship("Edge", foreign_keys="Edge.target_id", back_populates="target_node", lazy="selectin")

    __table_args__ = (
        Index("idx_nodes_space_status", "space_id", "status"),
        Index("idx_nodes_type", "type"),
        Index("idx_nodes_ipcra_stage", "ipcra_stage"),
        Index(
            "idx_nodes_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
