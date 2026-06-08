from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base

class Vote(Base):
    __tablename__ = "votes"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conseil_id  = Column(String, nullable=True)
    world_id    = Column(String, nullable=False)
    question    = Column(Text, nullable=False)
    statut      = Column(String, default="ouvert")  # ouvert / ferme
    created_by  = Column(String, nullable=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ferme_at    = Column(DateTime, nullable=True)
    bulletins   = relationship("Bulletin", back_populates="vote", cascade="all, delete")

class Bulletin(Base):
    __tablename__ = "bulletins"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vote_id    = Column(String, ForeignKey("votes.id"), nullable=False)
    user_id    = Column(String, nullable=False)
    user_nom   = Column(String, nullable=False)
    choix      = Column(String, nullable=False)  # pour / contre / abstention
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    vote       = relationship("Vote", back_populates="bulletins")
