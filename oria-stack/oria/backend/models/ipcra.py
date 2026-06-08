from sqlalchemy import Column, String, Text, DateTime, Integer
from datetime import datetime, timezone
import uuid
from database import Base

CATEGORIES = ["input", "projet", "casquette", "ressource", "archive"]


class IPCRAItem(Base):
    """Élément IPCRA selon la méthode d'Eliott Meunier.

    Input      → capture brute, idée à traiter
    Projet     → projet actif avec objectif et deadline
    Casquette  → rôle / responsabilité (chapeau porté)
    Ressource  → référence, template, connaissance réutilisable
    Archive    → élément terminé / inactif
    """
    __tablename__ = "ipcra_items"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id   = Column(String, nullable=False, index=True)
    world_id   = Column(String, nullable=True)
    categorie  = Column(String, nullable=False, default="input")  # voir CATEGORIES
    titre      = Column(String, nullable=False)
    contenu    = Column(Text, default="")
    tags       = Column(Text, default="[]")      # JSON list de strings
    casquette  = Column(String, nullable=True)   # nom du rôle (si catégorie=casquette)
    source_url = Column(String, nullable=True)   # URL source (pour les inputs web)
    agent_id   = Column(String, nullable=True)   # agent Forge assigné
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class IPCRATrace(Base):
    """Historique des interactions IA sur un élément IPCRA."""
    __tablename__ = "ipcra_traces"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id    = Column(String, nullable=True, index=True)
    owner_id   = Column(String, nullable=False)
    prompt     = Column(Text, default="")
    answer     = Column(Text, default="")
    agent_nom  = Column(String, default="")
    duree_ms   = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
