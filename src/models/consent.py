"""ConsentRecord model — GDPR consent tracking.

Every consent grant/revocation is immutably recorded.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User


class ConsentRecord(TimestampMixin, Base):
    """An individual consent grant or revocation event."""

    __tablename__ = "consent_records"

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # Consent details
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="ConsentType enum value")
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    method: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="How consent was given: chat, link, form"
    )

    # Optional reference to the message where consent was given
    message_text: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="consent_records")

    def __repr__(self) -> str:
        return f"<ConsentRecord type={self.consent_type} granted={self.granted}>"
