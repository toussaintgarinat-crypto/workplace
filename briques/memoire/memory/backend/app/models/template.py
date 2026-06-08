import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Template(Base):
    __tablename__ = "templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True)
    name = Column(Text, nullable=False)
    node_type = Column(String, nullable=False)
    title_template = Column(Text, nullable=False, default="")
    content_template = Column(Text, nullable=False, default="")
    frontmatter_template = Column(Text, nullable=True)
    is_global = Column(String, nullable=False, default="true")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
