"""ExtractedData model — individual data fields extracted during a session.

Every field tracks its source (OCR, manual, CF decode, etc.) for the
dossier confidence system and audit trail.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.session import Session


class ExtractedData(TimestampMixin, Base):
    """A single extracted data field with source tracking."""

    __tablename__ = "extracted_data"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Data field
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text, comment="Plain text or encrypted depending on field")
    value_encrypted: Mapped[bool] = mapped_column(default=False, comment="Whether value is AES encrypted")

    # Source tracking
    source: Mapped[str] = mapped_column(String(30), nullable=False, comment="DataSource enum value")
    confidence: Mapped[float | None] = mapped_column(Float, comment="0.0–1.0 confidence score")

    # Link to the document that produced this extraction (if applicable)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id")
    )

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="extracted_data")

    def __repr__(self) -> str:
        return f"<ExtractedData field={self.field_name} source={self.source} confidence={self.confidence}>"
