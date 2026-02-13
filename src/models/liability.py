"""Liability model — existing financial obligations of the user.

Critical for DTI calculation and CdQ renewal detection.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.session import Session


class Liability(TimestampMixin, Base):
    """An existing financial obligation (debt, loan, CdQ, etc.)."""

    __tablename__ = "liabilities"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Liability details
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="LiabilityType enum value")
    monthly_installment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    remaining_months: Mapped[int | None] = mapped_column(Integer)
    total_months: Mapped[int | None] = mapped_column(Integer)
    paid_months: Mapped[int | None] = mapped_column(Integer)
    residual_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    lender: Mapped[str | None] = mapped_column(String(200))

    # Source tracking
    detected_from: Mapped[str | None] = mapped_column(String(30), comment="DataSource enum value")
    supporting_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id")
    )

    # CdQ-specific
    renewable: Mapped[bool | None] = mapped_column(Boolean, comment="Eligible for rinnovo CdQ")

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="liabilities")

    def __repr__(self) -> str:
        return f"<Liability type={self.type} monthly={self.monthly_installment}>"
