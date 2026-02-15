"""Audit log subscriber — persists every SystemEvent to the audit_log table.

Registered as a global subscriber (receives ALL events). This is the
system's immutable audit trail for compliance and debugging.

Never raises — failures are logged but never propagate to the event system.
"""

from __future__ import annotations

import logging

from src.db.engine import async_session_factory
from src.models.audit import AuditLog
from src.schemas.events import SystemEvent

logger = logging.getLogger(__name__)


async def audit_on_event(event: SystemEvent) -> None:
    """Write a SystemEvent to the audit_log table.

    Called by the event system for every emitted event.
    Failures are logged and swallowed — audit logging must never
    crash the main application flow.
    """
    try:
        async with async_session_factory() as db:
            audit = AuditLog(
                event_type=event.event_type.value,
                session_id=event.session_id,
                actor_id=event.actor_id,
                actor_role=event.actor_role,
                data=event.data,
            )
            db.add(audit)
            await db.commit()
    except Exception:
        logger.exception(
            "Failed to persist audit event: %s (session=%s)",
            event.event_type.value,
            event.session_id,
        )
