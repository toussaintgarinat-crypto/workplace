from sqlalchemy import Column, String, Integer, ForeignKey, Text, DateTime, Boolean, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base
# models.project imported lazily to avoid circular imports — Room.project uses string ref

class Building(Base):
    __tablename__ = "buildings"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id    = Column(String, ForeignKey("worlds.id"), nullable=False)
    quartier_id = Column(String, ForeignKey("quartiers.id"), nullable=True)
    nom         = Column(String, nullable=False)
    type        = Column(String, default="maison")
    description = Column(Text, default="")
    emoji       = Column(String, default="🏠")
    couleur     = Column(String, default="#5865F2")
    position    = Column(Integer, default=0)
    world       = relationship("World", back_populates="buildings")
    quartier    = relationship("Quartier", back_populates="buildings")
    rooms       = relationship("Room", back_populates="building", cascade="all, delete", order_by="Room.etage, Room.position")
    files       = relationship("File", back_populates="building", cascade="all, delete")

class Room(Base):
    __tablename__ = "rooms"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    building_id = Column(String, ForeignKey("buildings.id"), nullable=False)
    nom         = Column(String, nullable=False)
    type        = Column(String, default="mixte")
    etage       = Column(Integer, default=0)
    position    = Column(Integer, default=0)
    emoji              = Column(String, default="💬")
    matrix_room_id     = Column(String, nullable=True)  # "!xxx:oria.local"
    acces_restreint         = Column(String, default="libre")  # libre | cadenas | cache
    est_payante             = Column(Boolean, default=False)
    prix_acces              = Column(Float, nullable=True)
    devise_acces            = Column(String, default="EUR")
    type_paiement           = Column(String, nullable=True)   # abonnement | unique
    stripe_price_id_acces   = Column(String, nullable=True)
    stripe_product_id_acces = Column(String, nullable=True)
    project_id  = Column(String, ForeignKey("projects.id"), nullable=True)
    status      = Column(String, default="active")   # active | closed
    closed_at   = Column(DateTime, nullable=True)
    building    = relationship("Building", back_populates="rooms")
    project     = relationship("Project", back_populates="rooms")
    messages           = relationship("Message", back_populates="room", cascade="all, delete")
    files              = relationship("File", back_populates="room", cascade="all, delete")
    abonnements_requis = relationship("RoomAbonnement", back_populates="room", cascade="all, delete")
    acces_payes        = relationship("RoomAccesPaye", back_populates="room", cascade="all, delete")
    coins              = relationship("Coin", back_populates="room", cascade="all, delete")

class Message(Base):
    __tablename__ = "messages"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id      = Column(String, ForeignKey("rooms.id"), nullable=False)
    author_nom   = Column(String, nullable=False)
    author_emoji = Column(String, default="👤")
    author_id    = Column(String, default="")
    contenu      = Column(Text, nullable=False)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    room         = relationship("Room", back_populates="messages")
    reactions    = relationship("Reaction", back_populates="message", cascade="all, delete")

class Reaction(Base):
    __tablename__ = "reactions"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String, ForeignKey("messages.id"), nullable=False)
    user_id    = Column(String, nullable=False)
    user_nom   = Column(String, nullable=False)
    emoji      = Column(String, nullable=False)
    message    = relationship("Message", back_populates="reactions")

class File(Base):
    __tablename__ = "files"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id      = Column(String, ForeignKey("rooms.id"), nullable=True)      # room attachment
    building_id  = Column(String, ForeignKey("buildings.id"), nullable=True)  # building doc
    world_id     = Column(String, nullable=True)                              # world doc (pas de FK pour éviter import circulaire)
    uploaded_by  = Column(String, nullable=False)
    uploader_nom = Column(String, nullable=False)
    nom          = Column(String, nullable=False)
    taille       = Column(Integer, default=0)
    type_mime    = Column(String, default="application/octet-stream")
    path         = Column(String, nullable=False)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    room         = relationship("Room", back_populates="files")
    building     = relationship("Building", back_populates="files")
