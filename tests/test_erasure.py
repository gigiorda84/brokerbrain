"""Tests for ErasureProcessor — GDPR Art. 17 cascade deletion."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.models.enums import DeletionRequestStatus
from src.security.erasure import ErasureProcessor, ErasureResult


# ── Helpers ──────────────────────────────────────────────────────────


def _make_db():
    """Build a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_deletion_request(user_id=None, status="pending"):
    """Build a minimal mock DataDeletionRequest."""
    req = MagicMock()
    req.id = uuid.uuid4()
    req.user_id = user_id or uuid.uuid4()
    req.status = status
    req.requested_at = datetime.now(timezone.utc)
    req.completed_at = None
    return req


def _make_user(user_id=None):
    """Build a minimal mock User."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.first_name = "Mario"
    user.last_name = "Rossi"
    user.email = "mario@test.com"
    user.phone = "+39123456789"
    user.whatsapp_id = "39123456789"
    user.telegram_id = "12345"
    user.codice_fiscale_encrypted = "encrypted_cf"
    user.consent_status = {"privacy_policy": True}
    user.anonymized = False
    return user


def _make_execute_result(rows=None, rowcount=0):
    """Build a mock execute result."""
    result = MagicMock()
    if rows is not None:
        result.all.return_value = rows
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
    result.rowcount = rowcount
    return result


# ── ErasureResult ────────────────────────────────────────────────────


class TestErasureResult:
    """Test ErasureResult dataclass."""

    def test_defaults(self):
        result = ErasureResult()
        assert result.success is False
        assert result.sessions == 0
        assert result.messages == 0
        assert result.documents == 0
        assert result.error is None

    def test_custom_values(self):
        result = ErasureResult(
            success=True,
            sessions=3,
            messages=50,
            documents=2,
        )
        assert result.success is True
        assert result.sessions == 3


# ── request_erasure ──────────────────────────────────────────────────


class TestRequestErasure:
    """Test ErasureProcessor.request_erasure."""

    @pytest.mark.asyncio()
    async def test_creates_pending_request(self):
        """request_erasure should create a PENDING DataDeletionRequest."""
        db = _make_db()
        processor = ErasureProcessor()
        user_id = uuid.uuid4()

        with patch("src.security.erasure.emit", new_callable=AsyncMock):
            request = await processor.request_erasure(db, user_id)

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert request.user_id == user_id
        assert request.status == DeletionRequestStatus.PENDING.value

    @pytest.mark.asyncio()
    async def test_emits_deletion_requested_event(self):
        """request_erasure should emit DELETION_REQUESTED event."""
        db = _make_db()
        processor = ErasureProcessor()

        with patch("src.security.erasure.emit", new_callable=AsyncMock) as mock_emit:
            await processor.request_erasure(db, uuid.uuid4())

        mock_emit.assert_awaited_once()
        event = mock_emit.call_args[0][0]
        assert event.event_type.value == "gdpr.deletion_requested"


# ── process_erasure ──────────────────────────────────────────────────


class TestProcessErasure:
    """Test ErasureProcessor.process_erasure."""

    @pytest.mark.asyncio()
    async def test_request_not_found(self):
        """process_erasure with non-existent request returns error."""
        db = _make_db()
        db.get = AsyncMock(return_value=None)
        processor = ErasureProcessor()

        result = await processor.process_erasure(db, uuid.uuid4())

        assert result.success is False
        assert result.error == "Deletion request not found"

    @pytest.mark.asyncio()
    async def test_full_cascade_success(self):
        """process_erasure should cascade through all tables and anonymize user."""
        db = _make_db()
        processor = ErasureProcessor()

        user_id = uuid.uuid4()
        deletion_req = _make_deletion_request(user_id=user_id)
        user = _make_user(user_id=user_id)
        session_ids = [uuid.uuid4(), uuid.uuid4()]

        # Mock db.get: first call returns deletion_req, second returns user
        get_call_count = 0

        async def _get_side_effect(model_class, id_val):
            nonlocal get_call_count
            get_call_count += 1
            if get_call_count == 1:
                return deletion_req
            return user

        db.get = AsyncMock(side_effect=_get_side_effect)

        # Track execute calls
        execute_results = []

        async def _execute_side_effect(stmt):
            # First call: SELECT session IDs
            if len(execute_results) == 0:
                result = _make_execute_result(
                    rows=[(sid,) for sid in session_ids]
                )
                execute_results.append("sessions")
                return result
            # Second call: DELETE extracted_data
            if len(execute_results) == 1:
                result = _make_execute_result(rowcount=5)
                execute_results.append("extracted_data")
                return result
            # Third call: SELECT documents (for file unlinking)
            if len(execute_results) == 2:
                result = _make_execute_result(rows=[])
                execute_results.append("docs_select")
                return result
            # Remaining calls: DELETE/UPDATE operations
            result = _make_execute_result(rowcount=3)
            execute_results.append("other")
            return result

        db.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("src.security.erasure.consent_manager.revoke_all", new_callable=AsyncMock),
            patch("src.security.erasure.emit", new_callable=AsyncMock) as mock_emit,
        ):
            result = await processor.process_erasure(db, deletion_req.id)

        assert result.success is True
        assert result.sessions == 2
        assert result.extracted_data == 5

        # User should be anonymized
        assert user.first_name == "[REDATTO]"
        assert user.last_name == "[REDATTO]"
        assert user.email is None
        assert user.phone is None
        assert user.whatsapp_id is None
        assert user.telegram_id == f"deleted_{user.id}"
        assert user.codice_fiscale_encrypted is None
        assert user.consent_status == {}
        assert user.anonymized is True

        # Request should be completed
        assert deletion_req.status == DeletionRequestStatus.COMPLETED.value
        assert deletion_req.completed_at is not None

        # Should emit DELETION_COMPLETED
        emit_calls = [c[0][0] for c in mock_emit.call_args_list]
        assert any(e.event_type.value == "gdpr.deletion_completed" for e in emit_calls)

    @pytest.mark.asyncio()
    async def test_no_sessions_still_anonymizes(self):
        """process_erasure with no sessions should still anonymize the user."""
        db = _make_db()
        processor = ErasureProcessor()

        user_id = uuid.uuid4()
        deletion_req = _make_deletion_request(user_id=user_id)
        user = _make_user(user_id=user_id)

        get_call_count = 0

        async def _get_side_effect(model_class, id_val):
            nonlocal get_call_count
            get_call_count += 1
            if get_call_count == 1:
                return deletion_req
            return user

        db.get = AsyncMock(side_effect=_get_side_effect)

        # SELECT sessions returns empty
        db.execute = AsyncMock(
            return_value=_make_execute_result(rows=[])
        )

        with (
            patch("src.security.erasure.consent_manager.revoke_all", new_callable=AsyncMock),
            patch("src.security.erasure.emit", new_callable=AsyncMock),
        ):
            result = await processor.process_erasure(db, deletion_req.id)

        assert result.success is True
        assert result.sessions == 0
        assert user.anonymized is True
        assert deletion_req.status == DeletionRequestStatus.COMPLETED.value

    @pytest.mark.asyncio()
    async def test_failure_sets_status_failed(self):
        """process_erasure on exception should set status=FAILED."""
        db = _make_db()
        processor = ErasureProcessor()

        deletion_req = _make_deletion_request()
        db.get = AsyncMock(return_value=deletion_req)

        # Make consent revocation raise an exception
        with (
            patch(
                "src.security.erasure.consent_manager.revoke_all",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch("src.security.erasure.emit", new_callable=AsyncMock),
        ):
            result = await processor.process_erasure(db, deletion_req.id)

        assert result.success is False
        assert "DB error" in result.error
        assert deletion_req.status == DeletionRequestStatus.FAILED.value

    @pytest.mark.asyncio()
    async def test_preserves_audit_and_consent_records(self):
        """process_erasure should NOT delete audit_log or consent_records tables."""
        db = _make_db()
        processor = ErasureProcessor()

        user_id = uuid.uuid4()
        deletion_req = _make_deletion_request(user_id=user_id)
        user = _make_user(user_id=user_id)

        get_call_count = 0

        async def _get_side_effect(model_class, id_val):
            nonlocal get_call_count
            get_call_count += 1
            if get_call_count == 1:
                return deletion_req
            return user

        db.get = AsyncMock(side_effect=_get_side_effect)
        db.execute = AsyncMock(return_value=_make_execute_result(rows=[]))

        with (
            patch("src.security.erasure.consent_manager.revoke_all", new_callable=AsyncMock),
            patch("src.security.erasure.emit", new_callable=AsyncMock),
        ):
            result = await processor.process_erasure(db, deletion_req.id)

        assert result.success is True

        # Verify no DELETE statements targeted audit_log or consent_records
        # by checking the execute calls — only the session ID SELECT should be there
        for call in db.execute.call_args_list:
            stmt = call[0][0]
            stmt_str = str(stmt)
            assert "audit_log" not in stmt_str.lower()
            assert "consent_record" not in stmt_str.lower()

    @pytest.mark.asyncio()
    async def test_document_file_unlinking(self):
        """process_erasure should attempt to unlink document files from disk."""
        db = _make_db()
        processor = ErasureProcessor()

        user_id = uuid.uuid4()
        deletion_req = _make_deletion_request(user_id=user_id)
        user = _make_user(user_id=user_id)
        session_id = uuid.uuid4()

        get_call_count = 0

        async def _get_side_effect(model_class, id_val):
            nonlocal get_call_count
            get_call_count += 1
            if get_call_count == 1:
                return deletion_req
            return user

        db.get = AsyncMock(side_effect=_get_side_effect)

        # Create a mock document with encrypted file path
        mock_doc = MagicMock()
        mock_doc.id = uuid.uuid4()
        mock_doc.file_path_encrypted = "encrypted_path"

        execute_count = 0

        async def _execute_side_effect(stmt):
            nonlocal execute_count
            execute_count += 1
            if execute_count == 1:
                # SELECT session IDs
                return _make_execute_result(rows=[(session_id,)])
            if execute_count == 2:
                # DELETE extracted_data
                return _make_execute_result(rowcount=0)
            if execute_count == 3:
                # SELECT documents
                return _make_execute_result(rows=[mock_doc])
            return _make_execute_result(rowcount=0)

        db.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("src.security.erasure.consent_manager.revoke_all", new_callable=AsyncMock),
            patch("src.security.erasure.emit", new_callable=AsyncMock),
            patch("src.security.erasure.field_encryptor") as mock_enc,
            patch("src.security.erasure.Path") as mock_path_cls,
        ):
            mock_enc.decrypt.return_value = "/tmp/test_doc.jpg"
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_cls.return_value = mock_path_instance

            result = await processor.process_erasure(db, deletion_req.id)

        # Should have decrypted the path and attempted to unlink
        mock_enc.decrypt.assert_called_once_with("encrypted_path")
        mock_path_instance.unlink.assert_called_once()

    @pytest.mark.asyncio()
    async def test_revoke_all_called(self):
        """process_erasure should call consent_manager.revoke_all."""
        db = _make_db()
        processor = ErasureProcessor()

        user_id = uuid.uuid4()
        deletion_req = _make_deletion_request(user_id=user_id)
        user = _make_user(user_id=user_id)

        get_call_count = 0

        async def _get_side_effect(model_class, id_val):
            nonlocal get_call_count
            get_call_count += 1
            if get_call_count == 1:
                return deletion_req
            return user

        db.get = AsyncMock(side_effect=_get_side_effect)
        db.execute = AsyncMock(return_value=_make_execute_result(rows=[]))

        with (
            patch("src.security.erasure.consent_manager.revoke_all", new_callable=AsyncMock) as mock_revoke,
            patch("src.security.erasure.emit", new_callable=AsyncMock),
        ):
            result = await processor.process_erasure(db, deletion_req.id)

        mock_revoke.assert_awaited_once_with(db, user_id, method="erasure")
