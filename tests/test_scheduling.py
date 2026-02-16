"""Tests for the scheduling service.

Covers:
- Appointment creation with and without operator assignment
- Notes formatting from preferences
- Pending appointment listing
- Appointment cancellation
- Least-loaded operator assignment
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.enums import AppointmentStatus
from src.scheduling.service import SchedulingService


# ── Helpers ──────────────────────────────────────────────────────────


def _make_session(session_id: uuid.UUID | None = None) -> MagicMock:
    s = MagicMock()
    s.id = session_id or uuid.uuid4()
    s.extracted_data = []
    return s


def _make_user(user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    return u


def _make_operator(name: str = "Mario Rossi", op_id: uuid.UUID | None = None) -> MagicMock:
    op = MagicMock()
    op.id = op_id or uuid.uuid4()
    op.name = name
    op.is_active = True
    return op


def _make_appointment(
    session_id: uuid.UUID | None = None,
    status: str = AppointmentStatus.PENDING.value,
    notes: str = "",
    operator: MagicMock | None = None,
) -> MagicMock:
    appt = MagicMock()
    appt.id = uuid.uuid4()
    appt.session_id = session_id or uuid.uuid4()
    appt.status = status
    appt.notes = notes
    appt.operator = operator
    appt.created_at = datetime.now(timezone.utc)
    return appt


# ── Appointment creation ─────────────────────────────────────────────


class TestCreateAppointment:
    """Test SchedulingService.create_appointment."""

    @pytest.mark.asyncio()
    async def test_create_appointment_with_operator(self):
        """Operator assigned, event emitted, notes formatted."""
        service = SchedulingService()
        db = AsyncMock()
        session = _make_session()
        user = _make_user()
        operator = _make_operator("Anna Bianchi")

        with patch.object(service, "_assign_operator", return_value=operator):
            with patch("src.scheduling.service.emit", new_callable=AsyncMock) as mock_emit:
                appt = await service.create_appointment(
                    db, session, user, {"preferred_time": "pomeriggio", "contact_method": "telefono"}
                )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()

        # Event emitted with correct data
        mock_emit.assert_awaited_once()
        event = mock_emit.call_args.args[0]
        assert event.data["operator_name"] == "Anna Bianchi"
        assert event.data["preferred_time"] == "pomeriggio"
        assert event.data["contact_method"] == "telefono"

        # Appointment fields
        added_obj = db.add.call_args.args[0]
        assert added_obj.session_id == session.id
        assert added_obj.operator_id == operator.id
        assert added_obj.status == AppointmentStatus.PENDING.value

    @pytest.mark.asyncio()
    async def test_create_appointment_no_operators(self):
        """No active operators → appointment created with operator_id=None."""
        service = SchedulingService()
        db = AsyncMock()
        session = _make_session()
        user = _make_user()

        with patch.object(service, "_assign_operator", return_value=None):
            with patch("src.scheduling.service.emit", new_callable=AsyncMock) as mock_emit:
                await service.create_appointment(db, session, user, {})

        added_obj = db.add.call_args.args[0]
        assert added_obj.operator_id is None

        event = mock_emit.call_args.args[0]
        assert event.data["operator_name"] == "non assegnato"


class TestBuildNotes:
    """Test SchedulingService._build_notes."""

    def test_notes_with_both_preferences(self):
        notes = SchedulingService._build_notes({
            "preferred_time": "pomeriggio",
            "contact_method": "telefono",
        })
        assert "Orario preferito: pomeriggio" in notes
        assert "Contatto: telefono" in notes

    def test_notes_with_only_time(self):
        notes = SchedulingService._build_notes({"preferred_time": "mattina"})
        assert notes == "Orario preferito: mattina"

    def test_notes_empty_preferences(self):
        notes = SchedulingService._build_notes({})
        assert notes == ""

    def test_notes_ignores_unknown_keys(self):
        notes = SchedulingService._build_notes({"unknown_key": "value"})
        assert notes == ""


# ── Pending appointments ─────────────────────────────────────────────


class TestGetPendingAppointments:
    """Test SchedulingService.get_pending_appointments."""

    @pytest.mark.asyncio()
    async def test_returns_pending_list(self):
        service = SchedulingService()
        db = AsyncMock()
        appts = [_make_appointment(), _make_appointment()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = appts
        db.execute.return_value = mock_result

        result = await service.get_pending_appointments(db)

        assert len(result) == 2
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_returns_empty_list(self):
        service = SchedulingService()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await service.get_pending_appointments(db)

        assert result == []


# ── Cancellation ─────────────────────────────────────────────────────


class TestCancelAppointment:
    """Test SchedulingService.cancel_appointment."""

    @pytest.mark.asyncio()
    async def test_cancel_existing_appointment(self):
        service = SchedulingService()
        db = AsyncMock()
        appt = _make_appointment()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = appt
        db.execute.return_value = mock_result

        with patch("src.scheduling.service.emit", new_callable=AsyncMock) as mock_emit:
            result = await service.cancel_appointment(db, str(appt.id))

        assert result is appt
        assert appt.status == AppointmentStatus.CANCELLED.value
        db.flush.assert_awaited_once()
        mock_emit.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_cancel_not_found(self):
        service = SchedulingService()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with patch("src.scheduling.service.emit", new_callable=AsyncMock):
            result = await service.cancel_appointment(db, str(uuid.uuid4()))

        assert result is None


# ── Operator assignment ──────────────────────────────────────────────


class TestOperatorAssignment:
    """Test SchedulingService._assign_operator."""

    @pytest.mark.asyncio()
    async def test_assigns_least_loaded_operator(self):
        """Returns the operator with fewest pending appointments."""
        service = SchedulingService()
        db = AsyncMock()
        least_loaded = _make_operator("Least Loaded")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = least_loaded
        db.execute.return_value = mock_result

        result = await service._assign_operator(db)

        assert result is least_loaded
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_returns_none_when_no_operators(self):
        """No active operators → returns None."""
        service = SchedulingService()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await service._assign_operator(db)

        assert result is None
