"""Scheduling service — create, list, and cancel callback-request appointments.

Implements a simple callback-request flow: collect user preferences,
create an Appointment in the DB, assign an operator (least-loaded),
and notify admins via the event system.

No external calendar API — Cal.com integration can be layered on later.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.admin.events import emit
from src.models.appointment import Appointment
from src.models.enums import AppointmentStatus
from src.models.operator import Operator
from src.models.session import Session
from src.models.user import User
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


class SchedulingService:
    """Manages callback-request appointments."""

    async def create_appointment(
        self,
        db: AsyncSession,
        session: Session,
        user: User,
        preferences: dict[str, Any],
    ) -> Appointment:
        """Create a callback-request appointment.

        Args:
            db: Database session.
            session: The conversation session that triggered scheduling.
            user: The user requesting a callback.
            preferences: Dict with optional keys ``preferred_time``, ``contact_method``.

        Returns:
            The newly created Appointment.
        """
        operator = await self._assign_operator(db)

        notes = self._build_notes(preferences)

        appointment = Appointment(
            session_id=session.id,
            operator_id=operator.id if operator else None,
            scheduled_at=None,  # callback request, not a slot booking
            status=AppointmentStatus.PENDING.value,
            notes=notes,
        )
        db.add(appointment)
        await db.flush()

        operator_name = operator.name if operator else "non assegnato"

        await emit(SystemEvent(
            event_type=EventType.APPOINTMENT_BOOKED,
            session_id=session.id,
            user_id=user.id,
            data={
                "appointment_id": str(appointment.id),
                "operator_name": operator_name,
                "preferred_time": preferences.get("preferred_time", "non specificato"),
                "contact_method": preferences.get("contact_method", "non specificato"),
            },
            source_module="scheduling.service",
        ))

        logger.info(
            "Appointment created: id=%s session=%s operator=%s",
            appointment.id,
            session.id,
            operator_name,
        )
        return appointment

    async def _assign_operator(self, db: AsyncSession) -> Operator | None:
        """Pick the active operator with the fewest pending appointments."""
        # Subquery: count pending appointments per operator
        pending_count = (
            select(
                Appointment.operator_id,
                func.count(Appointment.id).label("pending_count"),
            )
            .where(Appointment.status == AppointmentStatus.PENDING.value)
            .group_by(Appointment.operator_id)
            .subquery()
        )

        result = await db.execute(
            select(Operator)
            .outerjoin(pending_count, Operator.id == pending_count.c.operator_id)
            .where(Operator.is_active.is_(True))
            .order_by(func.coalesce(pending_count.c.pending_count, 0).asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pending_appointments(self, db: AsyncSession) -> list[Appointment]:
        """Return pending appointments, most recent first, with relationships loaded."""
        result = await db.execute(
            select(Appointment)
            .where(Appointment.status == AppointmentStatus.PENDING.value)
            .options(
                selectinload(Appointment.session),
                selectinload(Appointment.operator),
            )
            .order_by(Appointment.created_at.desc())
            .limit(20)
        )
        return list(result.scalars().all())

    async def cancel_appointment(
        self,
        db: AsyncSession,
        appointment_id: str,
    ) -> Appointment | None:
        """Cancel an appointment by ID. Returns None if not found."""
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()
        if appointment is None:
            return None

        appointment.status = AppointmentStatus.CANCELLED.value
        await db.flush()

        await emit(SystemEvent(
            event_type=EventType.APPOINTMENT_CANCELLED,
            session_id=appointment.session_id,
            data={"appointment_id": str(appointment.id)},
            source_module="scheduling.service",
        ))

        logger.info("Appointment cancelled: id=%s", appointment.id)
        return appointment

    @staticmethod
    def _build_notes(preferences: dict[str, Any]) -> str:
        """Format preferences dict into an Italian notes string."""
        parts: list[str] = []
        if preferences.get("preferred_time"):
            parts.append(f"Orario preferito: {preferences['preferred_time']}")
        if preferences.get("contact_method"):
            parts.append(f"Contatto: {preferences['contact_method']}")
        return ", ".join(parts) if parts else ""


# Module-level singleton
scheduling_service = SchedulingService()
