from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class GoogleCalendarConnection(Base):
    __tablename__ = "google_calendar_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    google_subject = Column(Text, nullable=True, index=True)
    google_email = Column(Text, nullable=True)
    calendar_id = Column(Text, nullable=False, default="primary")
    encrypted_access_token = Column(Text, nullable=False)
    encrypted_refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GoogleCalendarEventLink(Base):
    __tablename__ = "google_calendar_event_links"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "action_item_id", name="uq_google_calendar_user_action"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_item_id = Column(
        Integer,
        ForeignKey("action_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    calendar_id = Column(Text, nullable=False, default="primary")
    google_event_id = Column(Text, nullable=False)
    due_snapshot = Column(Text, nullable=False, default="")
    title_snapshot = Column(Text, nullable=False, default="")
    synced_at = Column(DateTime(timezone=True), server_default=func.now())
