from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.user import Department


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    department = Column(Enum(Department), nullable=False)
    masked_content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PiiEntry(Base):
    __tablename__ = "pii_entries"

    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    department = Column(Enum(Department), nullable=False)
    pii_type = Column(Text, nullable=False)
    original_value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
