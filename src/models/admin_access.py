"""AdminAccess model — tracks every admin action for accountability."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin

import uuid


class AdminAccess(TimestampMixin, Base):
    """Record of an admin action (view, export, override, etc.)."""

    __tablename__ = "admin_access"

    # Who did what
    admin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)

    # What was the target
    target_entity: Mapped[str | None] = mapped_column(String(50), comment="Table/model name")
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Additional context
    details: Mapped[str | None] = mapped_column(String(1000))

    def __repr__(self) -> str:
        return f"<AdminAccess admin={self.admin_id} action={self.action}>"
