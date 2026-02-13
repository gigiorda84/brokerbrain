"""Document model — uploaded documents processed through the OCR pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.session import Session


class Document(TimestampMixin, Base):
    """A document uploaded by the user for OCR extraction."""

    __tablename__ = "documents"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Document metadata
    doc_type: Mapped[str | None] = mapped_column(String(50), comment="Classified document type")
    original_filename: Mapped[str | None] = mapped_column(String(255))
    file_path_encrypted: Mapped[str | None] = mapped_column(Text, comment="AES-256-GCM encrypted file path")
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size_bytes: Mapped[int | None] = mapped_column()

    # OCR results
    ocr_result: Mapped[dict | None] = mapped_column(JSONB, comment="Full OCR extraction output")
    confidence_scores: Mapped[dict | None] = mapped_column(
        JSONB, comment="Per-field confidence scores from OCR"
    )
    overall_confidence: Mapped[float | None] = mapped_column(Float)

    # Processing metadata
    processing_model: Mapped[str | None] = mapped_column(String(50), comment="Which LLM model processed this")
    processing_time_ms: Mapped[int | None] = mapped_column(comment="OCR processing time in milliseconds")

    # Retention
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Auto-delete after retention period"
    )

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document id={self.id} type={self.doc_type} confidence={self.overall_confidence}>"
