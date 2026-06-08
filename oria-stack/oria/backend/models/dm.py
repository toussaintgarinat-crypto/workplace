from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime, timezone
import uuid
from database import Base

class DirectMessage(Base):
    __tablename__ = "direct_messages"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id     = Column(String, nullable=False)
    from_user_id = Column(String, nullable=False)
    from_nom     = Column(String, nullable=False)
    from_emoji   = Column(String, default="👤")
    to_user_id   = Column(String, nullable=False)
    contenu      = Column(Text, nullable=False)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class DirectMessageRoom(Base):
    """Lien entre deux utilisateurs Oria et leur room Matrix DM."""
    __tablename__ = "dm_rooms"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_a_id      = Column(String, nullable=False)
    user_b_id      = Column(String, nullable=False)
    matrix_room_id = Column(String, nullable=False)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
