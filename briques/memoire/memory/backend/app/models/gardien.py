import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base

import enum


class GardienSuggestionStatus(str, enum.Enum):
    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"
    auto = "auto"


class GardienConfigModel(Base):
    __tablename__ = "gardien_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, unique=True)
    mode = Column(String, nullable=False, default="propose")
    interval_minutes = Column(Integer, nullable=False, default=60)
    auto_summarize = Column(Boolean, nullable=False, default=True)
    auto_merge = Column(Boolean, nullable=False, default=True)
    auto_infer = Column(Boolean, nullable=False, default=True)
    auto_suggest_ipcra = Column(Boolean, nullable=False, default=True)
    auto_archive = Column(Boolean, nullable=False, default=False)


class GardienLog(Base):
    __tablename__ = "gardien_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    action = Column(Text, nullable=False)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    details = Column(JSONB, default=dict)
    status = Column(String, nullable=False, default=GardienSuggestionStatus.proposed)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    target_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    action = Column(Text, nullable=False)
    details = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))




