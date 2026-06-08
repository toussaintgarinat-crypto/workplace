from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from database import Base

# Types de liens entre mondes
# filiale     → A possède B
# partenaire  → collaboration égale
# client      → A est client de B
# fournisseur → A est fournisseur de B
# association → lien libre

class WorldLink(Base):
    __tablename__ = "world_links"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    from_world_id  = Column(String, ForeignKey("worlds.id"), nullable=False)
    to_world_id    = Column(String, ForeignKey("worlds.id"), nullable=False)
    type           = Column(String, default="partenaire")
    pourcentage    = Column(Float, nullable=True)   # optionnel
    created_by     = Column(String, nullable=False)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    visible        = Column(String, default="reseau")  # reseau | prive
    from_world     = relationship("World", foreign_keys=[from_world_id])
    to_world       = relationship("World", foreign_keys=[to_world_id])
