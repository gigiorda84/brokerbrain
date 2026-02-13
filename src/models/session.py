"""Session model — one qualification conversation from start to outcome.

Tracks FSM state, employment classification, and session outcome.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin
from src.models.enums import (
    ConversationState,
    EmployerCategory,
    EmploymentType,
    PensionSource,
    SessionOutcome,
)

if TYPE_CHECKING:
    from src.models.appointment import Appointment
    from src.models.calculation import CdQCalculation, DTICalculation
    from src.models.document import Document
    from src.models.extracted_data import ExtractedData
    from src.models.liability import Liability
    from src.models.message import Message
    from src.models.product_match import ProductMatch
    from src.models.quotation import QuotationData
    from src.models.user import User


class Session(TimestampMixin, Base):
    """A single qualification conversation session."""

    __tablename__ = "sessions"

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # FSM state
    current_state: Mapped[str] = mapped_column(
        String(50), default=ConversationState.WELCOME.value, nullable=False
    )

    # Classification data collected during conversation
    employment_type: Mapped[str | None] = mapped_column(String(30))
    employer_category: Mapped[str | None] = mapped_column(String(30))
    pension_source: Mapped[str | None] = mapped_column(String(20))
    track_type: Mapped[str | None] = mapped_column(String(20), comment="ocr or manual")
    income_doc_type: Mapped[str | None] = mapped_column(String(50))

    # Outcome
    outcome: Mapped[str | None] = mapped_column(String(30))
    outcome_reason: Mapped[str | None] = mapped_column(String(255))

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Message count (denormalized for quick dashboard queries)
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sessions")
    messages: Mapped[list[Message]] = relationship("Message", back_populates="session", lazy="selectin")
    documents: Mapped[list[Document]] = relationship("Document", back_populates="session", lazy="selectin")
    extracted_data: Mapped[list[ExtractedData]] = relationship(
        "ExtractedData", back_populates="session", lazy="selectin"
    )
    liabilities: Mapped[list[Liability]] = relationship("Liability", back_populates="session", lazy="selectin")
    dti_calculations: Mapped[list[DTICalculation]] = relationship(
        "DTICalculation", back_populates="session", lazy="selectin"
    )
    cdq_calculations: Mapped[list[CdQCalculation]] = relationship(
        "CdQCalculation", back_populates="session", lazy="selectin"
    )
    product_matches: Mapped[list[ProductMatch]] = relationship(
        "ProductMatch", back_populates="session", lazy="selectin"
    )
    quotation_data: Mapped[list[QuotationData]] = relationship(
        "QuotationData", back_populates="session", lazy="selectin"
    )
    appointments: Mapped[list[Appointment]] = relationship(
        "Appointment", back_populates="session", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} state={self.current_state} outcome={self.outcome}>"
