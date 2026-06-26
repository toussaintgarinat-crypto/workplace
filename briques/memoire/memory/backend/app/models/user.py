import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

import enum


class UserRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False)
    display_name = Column(Text, nullable=True)
    password_hash = Column(Text, nullable=True)
    auth_provider = Column(Text, default="email")
    auth_provider_id = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    nodes = relationship("Node", back_populates="user")
    space_memberships = relationship("SpaceUser", back_populates="user")


class Space(Base):
    __tablename__ = "spaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    description = Column(Text, default="")
    # Historique temporel de TOUT l'espace, opt-in (S112). Un curseur global du graphe
    # (« le graphe à T », S113) a besoin de l'histoire de tout l'espace, sinon la vue est
    # partielle. Distinct du `nodes.track_history` par document (S110). Faux par défaut.
    track_history = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    nodes = relationship("Node", back_populates="space")
    members = relationship("SpaceUser", back_populates="space", cascade="all, delete-orphan")


class SpaceUser(Base):
    __tablename__ = "space_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False, default=UserRole.member)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    space = relationship("Space", back_populates="members")
    user = relationship("User", back_populates="space_memberships")

    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="uq_space_user"),
    )
