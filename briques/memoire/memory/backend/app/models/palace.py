import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class PalaceRoom(Base):
    __tablename__ = "palace_rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    wing = Column(Text, nullable=False)
    room = Column(Text, nullable=False)
    drawer = Column(Text, nullable=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("palace_rooms.id", ondelete="SET NULL"), nullable=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    space = relationship("Space")
    children = relationship("PalaceRoom", backref="parent", remote_side=[id], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("space_id", "wing", "room", "drawer", name="uq_palace_location"),
    )
