from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base


class Abonnement(Base):
    __tablename__ = "abonnements"
    id                = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id          = Column(String, ForeignKey("worlds.id"), nullable=False)
    nom               = Column(String, nullable=False)
    description       = Column(Text, default="")
    couleur           = Column(String, default="#6366f1")
    prix              = Column(Float, default=0.0)
    devise            = Column(String, default="EUR")
    stripe_price_id   = Column(String, nullable=True)
    stripe_product_id = Column(String, nullable=True)
    actif             = Column(Boolean, default=True)
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    world             = relationship("World", back_populates="abonnements")
    membres           = relationship("MembreAbonnement", back_populates="abonnement", cascade="all, delete")
    rooms_requis      = relationship("RoomAbonnement", back_populates="abonnement", cascade="all, delete")


class MembreAbonnement(Base):
    __tablename__ = "membres_abonnements"
    id                     = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    member_id              = Column(String, ForeignKey("members.id"), nullable=False)
    abonnement_id          = Column(String, ForeignKey("abonnements.id"), nullable=False)
    actif                  = Column(Boolean, default=True)
    stripe_subscription_id = Column(String, nullable=True)
    date_debut             = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    date_fin               = Column(DateTime, nullable=True)
    assigne_manuellement   = Column(Boolean, default=False)
    member                 = relationship("Member", back_populates="abonnements")
    abonnement             = relationship("Abonnement", back_populates="membres")


class RoomAbonnement(Base):
    __tablename__ = "rooms_abonnements"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id       = Column(String, ForeignKey("rooms.id"), nullable=False)
    abonnement_id = Column(String, ForeignKey("abonnements.id"), nullable=False)
    room          = relationship("Room", back_populates="abonnements_requis")
    abonnement    = relationship("Abonnement", back_populates="rooms_requis")
