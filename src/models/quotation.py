"""QuotationData model — pre-filled form data for Primo Network quotation forms."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.session import Session


class QuotationData(TimestampMixin, Base):
    """Pre-filled quotation form data for one of 3 Primo Network form types."""

    __tablename__ = "quotation_data"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Form type: cqs, mutuo, or generic
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Form fields as JSONB — structure varies by form_type
    form_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="quotation_data")

    def __repr__(self) -> str:
        return f"<QuotationData form_type={self.form_type} session_id={self.session_id}>"
