from sqlalchemy import Column, String, DateTime, Enum as SAEnum, ForeignKey
from datetime import datetime, timezone
import uuid
import enum
from database import Base


class ZoneScope(str, enum.Enum):
    user  = "user"
    world = "world"


class ZoneRole(str, enum.Enum):
    owner       = "owner"
    contributor = "contributor"
    reader      = "reader"


class SharedZone(Base):
    __tablename__ = "shared_zones"
    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name                = Column(String, nullable=False)
    owner_id            = Column(String, ForeignKey("users.id"), nullable=False)
    scope               = Column(SAEnum(ZoneScope), nullable=False, default=ZoneScope.user)
    world_id            = Column(String, ForeignKey("worlds.id"), nullable=True)
    mempalace_namespace = Column(String, nullable=True)
    created_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SharedZoneMember(Base):
    __tablename__ = "shared_zone_members"
    zone_id   = Column(String, ForeignKey("shared_zones.id"), primary_key=True)
    user_id   = Column(String, ForeignKey("users.id"), primary_key=True)
    role      = Column(SAEnum(ZoneRole), nullable=False, default=ZoneRole.reader)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
