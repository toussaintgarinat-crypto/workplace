from sqlalchemy import Column, String, DateTime, Boolean, Text
from datetime import datetime, timezone
import uuid
from database import Base


class UserFollow(Base):
    __tablename__ = "user_follows"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    follower_id = Column(String, nullable=False)
    followed_id = Column(String, nullable=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    __tablename__ = "notifications"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, nullable=False)
    type       = Column(String, nullable=False)   # new_follower | new_world_public
    data       = Column(Text, default="{}")       # JSON contexte
    read       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
