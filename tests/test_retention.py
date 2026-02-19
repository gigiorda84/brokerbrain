"""Tests for src/security/retention.py — data retention enforcement."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.security.retention import (
    _delete_expired_audit_logs,
    _delete_expired_documents,
    _delete_expired_extracted_data,
    enforce_data_retention,
)


@pytest.fixture
def mock_db():
    """Create a mock async DB session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestDeleteExpiredDocuments:
    """Tests for _delete_expired_documents."""

    @pytest.mark.asyncio
    async def test_no_expired_docs(self, mock_db):
        """Returns 0 when no documents are expired."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        count = await _delete_expired_documents(mock_db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_deletes_expired_docs(self, mock_db):
        """Deletes docs and returns count."""
        doc1 = MagicMock()
        doc1.id = uuid.uuid4()
        doc1.file_path_encrypted = None

        doc2 = MagicMock()
        doc2.id = uuid.uuid4()
        doc2.file_path_encrypted = None

        # First call: select expired docs
        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [doc1, doc2]

        # Second call: delete
        delete_result = MagicMock()
        delete_result.rowcount = 2

        mock_db.execute.side_effect = [select_result, delete_result]

        count = await _delete_expired_documents(mock_db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_unlinks_encrypted_file(self, mock_db):
        """Attempts to decrypt and unlink file path."""
        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.file_path_encrypted = "encrypted_path"

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [doc]

        delete_result = MagicMock()
        delete_result.rowcount = 1

        mock_db.execute.side_effect = [select_result, delete_result]

        with patch("src.security.retention.field_encryptor") as mock_enc:
            mock_enc.decrypt.return_value = "/tmp/nonexistent_file.pdf"
            count = await _delete_expired_documents(mock_db)

        assert count == 1
        mock_enc.decrypt.assert_called_once_with("encrypted_path")


class TestDeleteExpiredExtractedData:
    """Tests for _delete_expired_extracted_data."""

    @pytest.mark.asyncio
    async def test_no_expired_sessions(self, mock_db):
        """Returns 0 when no sessions are old enough."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        count = await _delete_expired_extracted_data(mock_db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_deletes_from_expired_sessions(self, mock_db):
        """Deletes extracted data from completed expired sessions."""
        session_id = uuid.uuid4()

        session_result = MagicMock()
        session_result.all.return_value = [(session_id,)]

        delete_result = MagicMock()
        delete_result.rowcount = 15

        mock_db.execute.side_effect = [session_result, delete_result]

        count = await _delete_expired_extracted_data(mock_db)
        assert count == 15


class TestDeleteExpiredAuditLogs:
    """Tests for _delete_expired_audit_logs."""

    @pytest.mark.asyncio
    async def test_deletes_old_logs(self, mock_db):
        """Deletes audit logs older than 24 months."""
        delete_result = MagicMock()
        delete_result.rowcount = 100
        mock_db.execute.return_value = delete_result

        count = await _delete_expired_audit_logs(mock_db)
        assert count == 100

    @pytest.mark.asyncio
    async def test_no_old_logs(self, mock_db):
        """Returns 0 when no logs are expired."""
        delete_result = MagicMock()
        delete_result.rowcount = 0
        mock_db.execute.return_value = delete_result

        count = await _delete_expired_audit_logs(mock_db)
        assert count == 0


class TestEnforceDataRetention:
    """Tests for the top-level enforce_data_retention function."""

    @pytest.mark.asyncio
    async def test_runs_all_policies(self):
        """Calls all three deletion functions and returns summary."""
        with (
            patch("src.security.retention.async_session_factory") as mock_factory,
            patch("src.security.retention._delete_expired_documents", new_callable=AsyncMock) as mock_docs,
            patch("src.security.retention._delete_expired_extracted_data", new_callable=AsyncMock) as mock_data,
            patch("src.security.retention._delete_expired_audit_logs", new_callable=AsyncMock) as mock_audit,
            patch("src.security.retention.emit", new_callable=AsyncMock),
        ):
            mock_docs.return_value = 5
            mock_data.return_value = 10
            mock_audit.return_value = 3

            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await enforce_data_retention()

        assert result["documents_deleted"] == 5
        assert result["extracted_data_deleted"] == 10
        assert result["audit_logs_deleted"] == 3
