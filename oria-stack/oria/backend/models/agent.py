from sqlalchemy import Column, String, Text, Boolean, Float, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id        = Column(String, nullable=False)
    owner_id        = Column(String, nullable=False)
    nom             = Column(String, nullable=False)
    avatar_emoji    = Column(String, default="🤖")
    description     = Column(Text, default="")
    system_prompt   = Column(Text, default="Tu es un assistant IA utile et bienveillant.")
    # Position sur la carte 2D
    map_x           = Column(Float, default=5.0)
    map_y           = Column(Float, default=5.0)
    # Connexion Forge
    forge_url       = Column(String, default="http://localhost:3001")
    forge_provider  = Column(String, default="ollama")
    forge_model     = Column(String, default="")
    # Capacités
    can_read_docs   = Column(Boolean, default=True)   # accès aux dossiers du world
    use_memory      = Column(Boolean, default=True)   # utilise MemPalace
    use_ipcra       = Column(Boolean, default=False)  # mode IPCRA activé
    is_active       = Column(Boolean, default=True)
    wake_word       = Column(String, default="")
    is_jardin_agent = Column(Boolean, default=False)  # agent personnel du Jardin Secret
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
