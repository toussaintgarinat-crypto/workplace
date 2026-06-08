from sqlalchemy import Column, String, Integer, ForeignKey, Text
from sqlalchemy.orm import relationship
import uuid
from database import Base


class Quartier(Base):
    __tablename__ = "quartiers"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id    = Column(String, ForeignKey("worlds.id"), nullable=False)
    nom         = Column(String, nullable=False)
    emoji       = Column(String, default="🏘")
    couleur     = Column(String, default="#5865F2")
    description = Column(Text, default="")
    position    = Column(Integer, default=0)
    world       = relationship("World", back_populates="quartiers")
    buildings   = relationship("Building", back_populates="quartier")
