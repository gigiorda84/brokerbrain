"""ProductMatch model — results of the eligibility engine."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.models.session import Session


class ProductMatch(TimestampMixin, Base):
    """A product match result from the eligibility engine."""

    __tablename__ = "product_matches"

    # Foreign keys
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Product info
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sub_type: Mapped[str | None] = mapped_column(String(100))
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Rule details
    conditions: Mapped[dict | None] = mapped_column(JSONB, comment="Conditions met/unmet for this product")
    estimated_terms: Mapped[dict | None] = mapped_column(JSONB, comment="Estimated rates, amounts, durations")

    # Ranking
    rank: Mapped[int | None] = mapped_column(Integer, comment="Display order, lower is better")

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="product_matches")

    def __repr__(self) -> str:
        return f"<ProductMatch product={self.product_name} eligible={self.eligible} rank={self.rank}>"
