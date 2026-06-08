from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base


class ResidentAgent(Base):
    __tablename__ = "resident_agents"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name          = Column(String, nullable=False)
    pole_type     = Column(String, nullable=False)   # Finance/Marketing/Sales/Ops/Legal
    avatar_emoji  = Column(String, default="🤖")
    description   = Column(Text, default="")
    room_id       = Column(String, nullable=True)    # Room Oria associée
    forge_url     = Column(String, default="http://localhost:3001")
    forge_token   = Column(String, default="")       # token API Forge
    status        = Column(String, default="idle")   # idle / working / error
    current_task  = Column(Text, default="")
    last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
