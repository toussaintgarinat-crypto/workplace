from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid, secrets
from database import Base

class World(Base):
    __tablename__ = "worlds"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nom         = Column(String, nullable=False)
    description = Column(Text, default="")
    emoji       = Column(String, default="🌍")
    couleur     = Column(String, default="#5865F2")
    owner_id    = Column(String, nullable=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Réseau social
    is_public   = Column(Boolean, default=False)
    is_garden   = Column(Boolean, default=False)   # jardin secret — toujours privé
    tags        = Column(Text, default="")         # JSON list ex: '["IA","musique"]'
    view_count  = Column(Integer, default=0)
    # Carte 2D spatiale
    map_data    = Column(Text, default="")         # JSON : terrain, spawn, positions buildings/agents
    buildings    = relationship("Building", back_populates="world", cascade="all, delete")
    members      = relationship("Member", back_populates="world", cascade="all, delete")
    quartiers    = relationship("Quartier", back_populates="world", cascade="all, delete")
    invitations  = relationship("Invitation", back_populates="world", cascade="all, delete")
    abonnements  = relationship("Abonnement", back_populates="world", cascade="all, delete")
    projects     = relationship("Project", back_populates="world", cascade="all, delete")

class Member(Base):
    __tablename__ = "members"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id     = Column(String, ForeignKey("worlds.id"), nullable=False)
    user_id      = Column(String, nullable=False)
    nom          = Column(String, nullable=False)
    avatar_emoji = Column(String, default="👤")
    role         = Column(String, default="membre")  # proprietaire | admin | membre
    joined_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    world        = relationship("World", back_populates="members")
    abonnements  = relationship("MembreAbonnement", back_populates="member", cascade="all, delete")

class Invitation(Base):
    __tablename__ = "invitations"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id   = Column(String, ForeignKey("worlds.id"), nullable=False)
    token      = Column(String, unique=True, nullable=False, default=lambda: secrets.token_urlsafe(16))
    created_by = Column(String, nullable=False)
    max_uses   = Column(Integer, default=0)   # 0 = illimité
    uses       = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    world      = relationship("World", back_populates="invitations")
