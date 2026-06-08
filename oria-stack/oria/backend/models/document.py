from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime
from datetime import datetime, timezone
import uuid
from database import Base


class Document(Base):
    __tablename__ = "documents"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id        = Column(String, nullable=False)      # utilisateur propriétaire
    world_id        = Column(String, nullable=True)       # optionnel : lié à un world
    nom             = Column(String, nullable=False)
    nom_original    = Column(String, nullable=False)
    type_mime       = Column(String, default="application/octet-stream")
    taille          = Column(Integer, default=0)
    file_path       = Column(String, nullable=False)      # chemin stockage brut
    content_md      = Column(Text, default="")            # contenu converti Markitdown
    indexe_memory    = Column(Boolean, default=False)      # indexé dans MemPalace
    index_status     = Column(String, default="idle")      # idle|pending|processing|done|error (S125)
    memory_chunk_ids = Column(Text, default="")            # JSON list des IDs MemPalace
    partage_reseau   = Column(Boolean, default=False)      # visible par les worlds liés
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
