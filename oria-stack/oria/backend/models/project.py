from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base


class Project(Base):
    __tablename__ = "projects"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id    = Column(String, ForeignKey("worlds.id"), nullable=False)
    name        = Column(String, nullable=False)
    description = Column(Text, default="")
    status      = Column(String, default="active")   # active | closed | archived
    created_by  = Column(String, nullable=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at   = Column(DateTime, nullable=True)
    world       = relationship("World", back_populates="projects")
    rooms       = relationship("Room", back_populates="project")
