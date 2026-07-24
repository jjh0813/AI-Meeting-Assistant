import enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.user import Department


class ActionItemStatus(str, enum.Enum):
    pending = "대기"
    in_progress = "진행중"
    completed = "완료"
    superseded = "변경됨"


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    owner_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department = Column(Enum(Department), nullable=False)
    title = Column(Text, nullable=True)
    title_is_manual = Column(Boolean, nullable=False, default=False)
    masked_content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    summary_embedding = Column(Vector(768), nullable=True)
    analysis_status = Column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    analysis_error = Column(Text, nullable=True)
    archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PiiEntry(Base):
    __tablename__ = "pii_entries"

    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    department = Column(Enum(Department), nullable=False)
    pii_type = Column(Text, nullable=False)
    original_value = Column(Text, nullable=False)
    placeholder_token = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ActionItem(Base):
    __tablename__ = "action_items"

    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    department = Column(Enum(Department), nullable=False)
    task = Column(Text, nullable=False, default="")
    assignee = Column(Text, nullable=False, default="")
    due = Column(Text, nullable=False, default="")
    request = Column(Text, nullable=False, default="")
    status = Column(
        Enum(ActionItemStatus), nullable=False, default=ActionItemStatus.pending
    )
    task_embedding = Column(Vector(768), nullable=True)
    superseded_by_id = Column(
        Integer,
        ForeignKey("action_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(
        Integer, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department = Column(Enum(Department), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
