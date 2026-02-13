"""DataDeletionRequest model — GDPR right-to-erasure workflow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin
from src.models.enums import DeletionRequestStatus

if TYPE_CHECKING:
    from src.models.user import User


class DataDeletionRequest(TimestampMixin, Base):
    """A GDPR data deletion (right to erasure) request."""

    __tablename__ = "data_deletion_requests"

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), default=DeletionRequestStatus.PENDING.value, nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Admin notification
    admin_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_notes: Mapped[str | None] = mapped_column(String(1000))

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="deletion_requests")

    def __repr__(self) -> str:
        return f"<DataDeletionRequest user={self.user_id} status={self.status}>"
