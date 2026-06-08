from sqlalchemy import Column, String, DateTime
from datetime import datetime, timezone
import uuid
from database import Base

class LLMConfig(Base):
    """Configuration du provider LLM par commune (world).
    provider : anthropic | openai  (openai couvre Ollama, LM Studio, Groq, Together, Mistral…)
    base_url : ex. https://api.openai.com/v1  ou  http://localhost:11434/v1 (Ollama)
    api_key  : vide pour les modèles locaux
    model    : ex. claude-haiku-4-5-20251001 / gpt-4o / llama3 / mistral…
    """
    __tablename__ = "llm_configs"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    world_id   = Column(String, unique=True, nullable=False)  # 1 config par commune
    provider   = Column(String, default="anthropic")           # anthropic | openai
    base_url   = Column(String, default="")                    # URL de base de l'API
    api_key    = Column(String, default="")                    # clé API (peut être vide)
    model      = Column(String, default="claude-haiku-4-5-20251001")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    updated_by = Column(String, nullable=True)
