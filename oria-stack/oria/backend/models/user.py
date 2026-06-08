from sqlalchemy import Column, String, DateTime, Text, Boolean
from datetime import datetime, timezone
import uuid
from database import Base

class User(Base):
    __tablename__ = "users"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email           = Column(String, unique=True, nullable=False)
    nom             = Column(String, nullable=False)
    avatar_emoji    = Column(String, default="👤")
    hashed_password      = Column(String, nullable=False)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    matrix_user_id       = Column(String, nullable=True)   # "@oria_<uuid>:oria.local"
    matrix_access_token  = Column(String, nullable=True)
    matrix_provisioned   = Column(String, default="false") # "true" | "false" | "error"
    totp_secret          = Column(String, nullable=True)
    totp_enabled         = Column(Boolean, default=False)
    # Profil public réseau social
    bio                  = Column(Text, default="")
    website              = Column(String, default="")
    is_public            = Column(Boolean, default=True)
    # Config mémoire MemPalace
    mempalace_url        = Column(String, default="http://localhost:8765")
    # Jardin secret
    jardin_world_id      = Column(String, nullable=True)
    # Onboarding
    setup_completed_at              = Column(DateTime, nullable=True)
    documents_partageables_par_defaut = Column(Boolean, default=False)
