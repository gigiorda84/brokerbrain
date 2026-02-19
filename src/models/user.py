"""User model — the person interacting via WhatsApp or Telegram.

Supports GDPR soft-delete via the `anonymized` flag (keeps anonymized
record for audit purposes but wipes all PII).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin
from src.models.enums import ChannelType

if TYPE_CHECKING:
    from src.models.consent import ConsentRecord
    from src.models.deletion import DataDeletionRequest
    from src.models.session import Session


class User(TimestampMixin, Base):
    """A consumer who interacts with BrokerBot."""

    __tablename__ = "users"

    # Identifiers
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    telegram_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), default=ChannelType.TELEGRAM.value)

    # Profile
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    codice_fiscale_encrypted: Mapped[str | None] = mapped_column(Text, comment="AES-256-GCM encrypted")

    # Consent status (JSONB for flexibility: {"privacy": true, "marketing": false, ...})
    consent_status: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)

    # GDPR soft delete
    anonymized: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Relationships
    sessions: Mapped[list[Session]] = relationship("Session", back_populates="user", lazy="selectin")
    consent_records: Mapped[list[ConsentRecord]] = relationship(
        "ConsentRecord", back_populates="user", lazy="selectin"
    )
    deletion_requests: Mapped[list[DataDeletionRequest]] = relationship(
        "DataDeletionRequest", back_populates="user", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} channel={self.channel} anonymized={self.anonymized}>"
