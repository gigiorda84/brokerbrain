"""Message model — individual messages in a conversation session."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin
from src.models.enums import MessageRole

if TYPE_CHECKING:
    from src.models.session import Session


class Message(TimestampMixin, Base):
    """A single message exchanged during a session."""

    __tablename__ = "messages"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Content
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="user, assistant, or system")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    media_url: Mapped[str | None] = mapped_column(Text, comment="URL to attached media (image/document)")
    media_type: Mapped[str | None] = mapped_column(String(50), comment="MIME type of attached media")

    # FSM context — which state was active when this message was sent
    state_at_send: Mapped[str | None] = mapped_column(String(50))

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="messages")

    def __repr__(self) -> str:
        preview = self.content[:50] if self.content else ""
        return f"<Message id={self.id} role={self.role} preview='{preview}...'>"
