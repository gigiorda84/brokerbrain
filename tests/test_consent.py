"""Tests for ConsentManager — consent recording, checking, and export."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.enums import ConsentType
from src.security.consent import (
    CONSENT_FIELD_MAP,
    REQUIRED_CONSENTS,
    ConsentManager,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_db():
    """Build a mock AsyncSession with common operations."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_user(user_id=None, consent_status=None):
    """Build a minimal mock User."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.consent_status = consent_status if consent_status is not None else {}
    return user


def _make_consent_record(consent_type, granted, created_at=None):
    """Build a minimal mock ConsentRecord."""
    record = MagicMock()
    record.consent_type = consent_type
    record.granted = granted
    record.created_at = created_at or datetime.now(timezone.utc)
    record.method = "chat"
    return record


# ── Constants ────────────────────────────────────────────────────────


class TestConstants:
    """Test CONSENT_FIELD_MAP and REQUIRED_CONSENTS."""

    def test_consent_field_map_keys(self):
        assert "consent_privacy" in CONSENT_FIELD_MAP
        assert "consent_sensitive" in CONSENT_FIELD_MAP
        assert CONSENT_FIELD_MAP["consent_privacy"] == ConsentType.PRIVACY_POLICY
        assert CONSENT_FIELD_MAP["consent_sensitive"] == ConsentType.DATA_PROCESSING

    def test_required_consents(self):
        assert ConsentType.PRIVACY_POLICY in REQUIRED_CONSENTS
        assert ConsentType.DATA_PROCESSING in REQUIRED_CONSENTS
        assert len(REQUIRED_CONSENTS) == 2


# ── record_consent ───────────────────────────────────────────────────


class TestRecordConsent:
    """Test ConsentManager.record_consent."""

    @pytest.mark.asyncio()
    async def test_creates_record_and_updates_jsonb(self):
        """record_consent should add a ConsentRecord and update User.consent_status."""
        db = _make_db()
        user = _make_user()
        db.get = AsyncMock(return_value=user)
        manager = ConsentManager()

        with patch("src.security.consent.emit", new_callable=AsyncMock):
            record = await manager.record_consent(
                db, user.id, ConsentType.PRIVACY_POLICY, granted=True, method="chat",
            )

        # Should have added a record
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert record.consent_type == ConsentType.PRIVACY_POLICY.value
        assert record.granted is True

        # User JSONB should be updated
        assert user.consent_status[ConsentType.PRIVACY_POLICY.value] is True

    @pytest.mark.asyncio()
    async def test_emits_consent_granted_event(self):
        """record_consent with granted=True should emit CONSENT_GRANTED."""
        db = _make_db()
        user = _make_user()
        db.get = AsyncMock(return_value=user)
        manager = ConsentManager()

        with patch("src.security.consent.emit", new_callable=AsyncMock) as mock_emit:
            await manager.record_consent(
                db, user.id, ConsentType.DATA_PROCESSING, granted=True,
            )

        mock_emit.assert_awaited_once()
        event = mock_emit.call_args[0][0]
        assert event.event_type.value == "consent.granted"

    @pytest.mark.asyncio()
    async def test_emits_consent_revoked_event(self):
        """record_consent with granted=False should emit CONSENT_REVOKED."""
        db = _make_db()
        user = _make_user()
        db.get = AsyncMock(return_value=user)
        manager = ConsentManager()

        with patch("src.security.consent.emit", new_callable=AsyncMock) as mock_emit:
            await manager.record_consent(
                db, user.id, ConsentType.PRIVACY_POLICY, granted=False,
            )

        event = mock_emit.call_args[0][0]
        assert event.event_type.value == "consent.revoked"

    @pytest.mark.asyncio()
    async def test_preserves_existing_jsonb(self):
        """record_consent should preserve other consent types in JSONB."""
        db = _make_db()
        user = _make_user(consent_status={"marketing": True})
        db.get = AsyncMock(return_value=user)
        manager = ConsentManager()

        with patch("src.security.consent.emit", new_callable=AsyncMock):
            await manager.record_consent(
                db, user.id, ConsentType.PRIVACY_POLICY, granted=True,
            )

        assert user.consent_status["marketing"] is True
        assert user.consent_status[ConsentType.PRIVACY_POLICY.value] is True


# ── check_required_consent ───────────────────────────────────────────


class TestCheckRequiredConsent:
    """Test ConsentManager.check_required_consent."""

    @pytest.mark.asyncio()
    async def test_all_granted_returns_true(self):
        """Both required consents granted → True."""
        db = _make_db()
        manager = ConsentManager()

        # Mock: each query returns a granted record
        async def _execute_side_effect(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = _make_consent_record("", True)
            return result

        db.execute = AsyncMock(side_effect=_execute_side_effect)
        assert await manager.check_required_consent(db, uuid.uuid4()) is True

    @pytest.mark.asyncio()
    async def test_missing_one_returns_false(self):
        """One consent missing → False."""
        db = _make_db()
        manager = ConsentManager()

        call_count = 0

        async def _execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = _make_consent_record("", True)
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = AsyncMock(side_effect=_execute_side_effect)
        assert await manager.check_required_consent(db, uuid.uuid4()) is False

    @pytest.mark.asyncio()
    async def test_no_records_returns_false(self):
        """No consent records at all → False."""
        db = _make_db()
        manager = ConsentManager()

        async def _execute_side_effect(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        db.execute = AsyncMock(side_effect=_execute_side_effect)
        assert await manager.check_required_consent(db, uuid.uuid4()) is False


# ── get_consent_status ───────────────────────────────────────────────


class TestGetConsentStatus:
    """Test ConsentManager.get_consent_status."""

    @pytest.mark.asyncio()
    async def test_returns_latest_per_type(self):
        """get_consent_status should return the latest record per type."""
        db = _make_db()
        manager = ConsentManager()

        type_results = {
            ConsentType.PRIVACY_POLICY.value: True,
            ConsentType.DATA_PROCESSING.value: False,
            ConsentType.MARKETING.value: True,
            ConsentType.THIRD_PARTY.value: False,
        }

        async def _execute_side_effect(stmt):
            result = MagicMock()
            # Detect which consent_type is queried by checking the compiled query
            for ct_value, granted in type_results.items():
                # Use a simple marker approach
                pass
            # For simplicity, return records in order of ConsentType iteration
            return result

        # Simpler approach: return a unique record per call based on call index
        call_idx = 0
        consent_types_list = list(ConsentType)

        async def _execute_ordered(stmt):
            nonlocal call_idx
            ct = consent_types_list[call_idx]
            call_idx += 1
            result = MagicMock()
            granted = type_results.get(ct.value, False)
            result.scalar_one_or_none.return_value = _make_consent_record(ct.value, granted)
            return result

        db.execute = AsyncMock(side_effect=_execute_ordered)
        status = await manager.get_consent_status(db, uuid.uuid4())

        assert status[ConsentType.PRIVACY_POLICY.value] is True
        assert status[ConsentType.DATA_PROCESSING.value] is False
        assert status[ConsentType.MARKETING.value] is True
        assert status[ConsentType.THIRD_PARTY.value] is False


# ── revoke_all ───────────────────────────────────────────────────────


class TestRevokeAll:
    """Test ConsentManager.revoke_all."""

    @pytest.mark.asyncio()
    async def test_revokes_only_granted(self):
        """revoke_all should only create revocation records for granted consents."""
        db = _make_db()
        user = _make_user()
        db.get = AsyncMock(return_value=user)
        manager = ConsentManager()

        # Mock get_consent_status to show 2 granted, 2 not
        with (
            patch.object(manager, "get_consent_status", new_callable=AsyncMock) as mock_status,
            patch("src.security.consent.emit", new_callable=AsyncMock),
        ):
            mock_status.return_value = {
                ConsentType.PRIVACY_POLICY.value: True,
                ConsentType.DATA_PROCESSING.value: True,
                ConsentType.MARKETING.value: False,
                ConsentType.THIRD_PARTY.value: False,
            }
            records = await manager.revoke_all(db, user.id)

        # Should have created 2 revocation records (only the granted ones)
        assert len(records) == 2


# ── export_consent_history ───────────────────────────────────────────


class TestExportConsentHistory:
    """Test ConsentManager.export_consent_history."""

    @pytest.mark.asyncio()
    async def test_returns_full_trail(self):
        """export_consent_history should return all records in chronological order."""
        db = _make_db()
        manager = ConsentManager()

        mock_records = [
            _make_consent_record(ConsentType.PRIVACY_POLICY.value, True),
            _make_consent_record(ConsentType.DATA_PROCESSING.value, True),
            _make_consent_record(ConsentType.PRIVACY_POLICY.value, False),
        ]

        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = mock_records
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        history = await manager.export_consent_history(db, uuid.uuid4())

        assert len(history) == 3
        assert history[0]["consent_type"] == ConsentType.PRIVACY_POLICY.value
        assert history[0]["granted"] is True
        assert history[2]["granted"] is False
        assert "timestamp" in history[0]
