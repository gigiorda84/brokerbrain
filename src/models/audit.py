"""AuditLog model — immutable audit trail for every system event.

Every action in the system emits a SystemEvent which is persisted here.
This table is append-only — no updates or deletes.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class AuditLog(TimestampMixin, Base):
    """Immutable audit trail entry."""

    __tablename__ = "audit_log"

    # Event classification
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Context (all nullable — not every event relates to a session or actor)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(100), comment="User ID, admin ID, or 'system'")
    actor_role: Mapped[str | None] = mapped_column(String(50), comment="user, admin, system, bot")

    # Event data — flexible JSONB payload
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<AuditLog event={self.event_type} session={self.session_id}>"
