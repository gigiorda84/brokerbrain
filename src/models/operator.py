"""Operator model — Primo Network staff who receive qualified leads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.appointment import Appointment


class Operator(TimestampMixin, Base):
    """A Primo Network operator who handles qualified leads."""

    __tablename__ = "operators"

    # Profile
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))

    # Scheduling
    calendar_id: Mapped[str | None] = mapped_column(String(255), comment="Cal.com calendar ID")

    # Skills
    specializations: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(50)), comment="Product types this operator handles"
    )

    # Active flag
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    appointments: Mapped[list[Appointment]] = relationship("Appointment", back_populates="operator")

    def __repr__(self) -> str:
        return f"<Operator name={self.name} active={self.is_active}>"
