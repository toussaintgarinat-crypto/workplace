from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text, Integer
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base


class RoomAccesPaye(Base):
    __tablename__ = "rooms_acces_payes"
    id                     = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id                = Column(String, ForeignKey("rooms.id"), nullable=False)
    user_id                = Column(String, nullable=False)
    type_paiement          = Column(String, default="abonnement")  # abonnement | unique
    stripe_session_id      = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    actif                  = Column(Boolean, default=True)
    created_at             = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    room                   = relationship("Room", back_populates="acces_payes")


class Coin(Base):
    __tablename__ = "coins"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id     = Column(String, ForeignKey("rooms.id"), nullable=False)
    user_id     = Column(String, nullable=False)
    user_nom    = Column(String, nullable=False)
    user_emoji  = Column(String, default="👤")
    titre       = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    room        = relationship("Room", back_populates="coins")
    dossiers    = relationship("CoinDossier", back_populates="coin", cascade="all, delete")


class CoinDossier(Base):
    __tablename__ = "coin_dossiers"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    coin_id     = Column(String, ForeignKey("coins.id"), nullable=False)
    nom         = Column(String, nullable=False)
    visibilite  = Column(String, default="prive")  # prive | partage
    parent_id   = Column(String, ForeignKey("coin_dossiers.id"), nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    coin        = relationship("Coin", back_populates="dossiers")
    fichiers    = relationship("CoinFichier", back_populates="dossier", cascade="all, delete")
    sous_dossiers = relationship(
        "CoinDossier", cascade="all, delete",
        foreign_keys="CoinDossier.parent_id",
    )


class CoinFichier(Base):
    __tablename__ = "coin_fichiers"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dossier_id   = Column(String, ForeignKey("coin_dossiers.id"), nullable=False)
    coin_id      = Column(String, nullable=False)
    nom          = Column(String, nullable=False)
    path         = Column(String, nullable=False)
    taille       = Column(Integer, default=0)
    type_mime    = Column(String, default="application/octet-stream")
    uploaded_by  = Column(String, nullable=False)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    dossier      = relationship("CoinDossier", back_populates="fichiers")
