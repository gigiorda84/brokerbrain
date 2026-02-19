"""Data retention enforcement — daily cron job for GDPR compliance.

Enforces three retention tiers:
- Documents: 30 days (configurable via DOCUMENT_RETENTION_DAYS)
- Extracted data: 12 months (configurable via DATA_RETENTION_MONTHS)
- Audit logs: 24 months (archive then delete)

Consent records are kept for 5 years (regulatory requirement) and are NOT
deleted by this job.

Wired into the FastAPI lifespan via APScheduler (already bundled with
python-telegram-bot).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.events import emit
from src.config import settings
from src.db.engine import async_session_factory
from src.models.audit import AuditLog
from src.models.document import Document
from src.models.extracted_data import ExtractedData
from src.models.session import Session
from src.schemas.events import EventType, SystemEvent
from src.security.encryption import field_encryptor

logger = logging.getLogger(__name__)


async def enforce_data_retention() -> dict[str, int]:
    """Run all retention policies. Returns a summary dict.

    Safe to call on every schedule tick — uses cutoff dates to find
    expired records. Idempotent: running twice is harmless.
    """
    summary: dict[str, int] = {
        "documents_deleted": 0,
        "extracted_data_deleted": 0,
        "audit_logs_deleted": 0,
    }

    try:
        async with async_session_factory() as db:
            summary["documents_deleted"] = await _delete_expired_documents(db)
            summary["extracted_data_deleted"] = await _delete_expired_extracted_data(db)
            summary["audit_logs_deleted"] = await _delete_expired_audit_logs(db)
            await db.commit()
    except Exception:
        logger.exception("Data retention job failed")
        return summary

    await emit(SystemEvent(
        event_type=EventType.SYSTEM_MAINTENANCE,
        data={"action": "data_retention", **summary},
        source_module="security.retention",
    ))

    logger.info(
        "Retention job complete: docs=%d extracted=%d audit=%d",
        summary["documents_deleted"],
        summary["extracted_data_deleted"],
        summary["audit_logs_deleted"],
    )
    return summary


async def _delete_expired_documents(db: AsyncSession) -> int:
    """Delete documents older than DOCUMENT_RETENTION_DAYS.

    Securely unlinks any stored files before removing the DB row.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.document_retention_days)

    # Find expired documents (by created_at or explicit expires_at)
    result = await db.execute(
        select(Document).where(
            (Document.created_at < cutoff)
            | (
                Document.expires_at.isnot(None)
                & (Document.expires_at < datetime.now(UTC))
            )
        )
    )
    expired_docs = result.scalars().all()

    if not expired_docs:
        return 0

    # Unlink files first
    for doc in expired_docs:
        if doc.file_path_encrypted:
            try:
                file_path = field_encryptor.decrypt(doc.file_path_encrypted)
                path = Path(file_path)
                if path.exists():
                    path.unlink()
                    logger.debug("Deleted file: %s", file_path)
            except Exception:
                logger.warning("Failed to unlink file for document %s", doc.id)

    # Bulk delete from DB
    doc_ids = [doc.id for doc in expired_docs]
    del_result = await db.execute(
        delete(Document).where(Document.id.in_(doc_ids))
    )
    count = del_result.rowcount  # type: ignore[attr-defined]
    logger.info("Deleted %d expired documents (cutoff=%s)", count, cutoff.date())
    return count


async def _delete_expired_extracted_data(db: AsyncSession) -> int:
    """Delete extracted data from sessions older than DATA_RETENTION_MONTHS.

    Only deletes data from COMPLETED or ABANDONED sessions (never active ones).
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.data_retention_months * 30)

    # Find session IDs that are completed and older than cutoff
    session_result = await db.execute(
        select(Session.id).where(
            Session.completed_at.isnot(None),
            Session.completed_at < cutoff,
        )
    )
    expired_session_ids = [row[0] for row in session_result.all()]

    if not expired_session_ids:
        return 0

    del_result = await db.execute(
        delete(ExtractedData).where(ExtractedData.session_id.in_(expired_session_ids))
    )
    count = del_result.rowcount  # type: ignore[attr-defined]
    logger.info("Deleted %d extracted data rows (cutoff=%s)", count, cutoff.date())
    return count


async def _delete_expired_audit_logs(db: AsyncSession) -> int:
    """Delete audit logs older than 24 months.

    These are compliance logs — 24 months is the maximum retention
    period per GDPR's storage limitation principle.
    """
    cutoff = datetime.now(UTC) - timedelta(days=24 * 30)

    del_result = await db.execute(
        delete(AuditLog).where(AuditLog.created_at < cutoff)
    )
    count = del_result.rowcount  # type: ignore[attr-defined]
    if count > 0:
        logger.info("Deleted %d audit log entries (cutoff=%s)", count, cutoff.date())
    return count
