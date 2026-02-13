"""Calculation models — DTI and CdQ calculation results.

All financial amounts use Numeric(12,2) / Decimal — never float.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.session import Session


class DTICalculation(TimestampMixin, Base):
    """Debt-to-income ratio calculation snapshot."""

    __tablename__ = "dti_calculations"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Inputs
    monthly_income: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_obligations: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    proposed_installment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Results
    current_dti: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, comment="As decimal, e.g. 0.3500")
    projected_dti: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), comment="DTI including proposed installment"
    )

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="dti_calculations")

    def __repr__(self) -> str:
        return f"<DTICalculation current_dti={self.current_dti} projected_dti={self.projected_dti}>"


class CdQCalculation(TimestampMixin, Base):
    """Cessione del Quinto capacity calculation snapshot."""

    __tablename__ = "cdq_calculations"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Income
    net_income: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # CdQ capacity (1/5 of net income)
    max_cdq_rata: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    existing_cdq: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    available_cdq: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Delega capacity (additional 1/5)
    max_delega_rata: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    existing_delega: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    available_delega: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="cdq_calculations")

    def __repr__(self) -> str:
        return f"<CdQCalculation available_cdq={self.available_cdq} available_delega={self.available_delega}>"
