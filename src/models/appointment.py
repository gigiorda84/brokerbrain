"""Appointment model — scheduled consultations with Primo Network operators."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin
from src.models.enums import AppointmentStatus

if TYPE_CHECKING:
    from src.models.operator import Operator
    from src.models.session import Session


class Appointment(TimestampMixin, Base):
    """A scheduled appointment between a qualified lead and an operator."""

    __tablename__ = "appointments"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id")
    )

    # Scheduling
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), default=AppointmentStatus.PENDING.value, nullable=False
    )

    # External calendar reference
    cal_event_id: Mapped[str | None] = mapped_column(String(255), comment="Cal.com / Calendly event ID")

    # Notes
    notes: Mapped[str | None] = mapped_column(String(1000))

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="appointments")
    operator: Mapped[Operator | None] = relationship("Operator", back_populates="appointments")

    def __repr__(self) -> str:
        return f"<Appointment id={self.id} status={self.status} at={self.scheduled_at}>"
