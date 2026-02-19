"""Right-to-erasure processor — GDPR Art. 17 cascade deletion.

Deletes all user data while preserving AuditLog and ConsentRecord entries
(5-year regulatory retention). Uses bulk SQL for performance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.events import emit
from src.models.appointment import Appointment
from src.models.calculation import CdQCalculation, DTICalculation
from src.models.deletion import DataDeletionRequest
from src.models.document import Document
from src.models.enums import AppointmentStatus, DeletionRequestStatus
from src.models.extracted_data import ExtractedData
from src.models.liability import Liability
from src.models.message import Message
from src.models.product_match import ProductMatch
from src.models.quotation import QuotationData
from src.models.session import Session
from src.models.user import User
from src.schemas.events import EventType, SystemEvent
from src.security.consent import consent_manager
from src.security.encryption import field_encryptor

logger = logging.getLogger(__name__)


@dataclass
class ErasureResult:
    """Summary of a completed (or failed) erasure operation."""

    success: bool = False
    deletion_request_id: Any = None
    sessions: int = 0
    messages: int = 0
    documents: int = 0
    extracted_data: int = 0
    liabilities: int = 0
    dti_calculations: int = 0
    cdq_calculations: int = 0
    product_matches: int = 0
    quotation_data: int = 0
    appointments_cancelled: int = 0
    error: str | None = None


class ErasureProcessor:
    """Processes GDPR right-to-erasure requests."""

    async def request_erasure(self, db: AsyncSession, user_id: Any) -> DataDeletionRequest:
        """Create a PENDING deletion request and emit event."""
        request = DataDeletionRequest(
            user_id=user_id,
            status=DeletionRequestStatus.PENDING.value,
            requested_at=datetime.now(UTC),
        )
        db.add(request)
        await db.flush()

        await emit(SystemEvent(
            event_type=EventType.DELETION_REQUESTED,
            user_id=user_id,
            data={"deletion_request_id": str(request.id)},
            source_module="security.erasure",
        ))

        logger.info("Erasure requested: user=%s request=%s", user_id, request.id)
        return request

    async def process_erasure(self, db: AsyncSession, deletion_request_id: Any) -> ErasureResult:
        """Execute the full cascade deletion for a request.

        Preserves: AuditLog entries, ConsentRecord entries (regulatory retention).
        """
        result = ErasureResult(deletion_request_id=deletion_request_id)

        # Load the deletion request
        request = await db.get(DataDeletionRequest, deletion_request_id)
        if request is None:
            result.error = "Deletion request not found"
            return result

        user_id = request.user_id

        try:
            # 1. Set status = IN_PROGRESS
            request.status = DeletionRequestStatus.IN_PROGRESS.value
            await db.flush()

            # 2. Revoke all consents
            await consent_manager.revoke_all(db, user_id, method="erasure")

            # 3. Get all user sessions
            sessions_result = await db.execute(
                select(Session.id).where(Session.user_id == user_id)
            )
            session_ids = [row[0] for row in sessions_result.all()]
            result.sessions = len(session_ids)

            if session_ids:
                # 3a. Delete extracted_data
                del_result = await db.execute(
                    delete(ExtractedData).where(ExtractedData.session_id.in_(session_ids))
                )
                result.extracted_data = del_result.rowcount  # type: ignore[attr-defined]

                # 3b. Delete documents (unlink files if they exist)
                docs_result = await db.execute(
                    select(Document).where(Document.session_id.in_(session_ids))
                )
                docs = docs_result.scalars().all()
                for doc in docs:
                    if doc.file_path_encrypted:
                        try:
                            file_path = field_encryptor.decrypt(doc.file_path_encrypted)
                            path = Path(file_path)
                            if path.exists():
                                path.unlink()
                        except Exception:
                            logger.warning("Failed to unlink document file for doc %s", doc.id)

                del_result = await db.execute(
                    delete(Document).where(Document.session_id.in_(session_ids))
                )
                result.documents = del_result.rowcount  # type: ignore[attr-defined]

                # 3c. Delete liabilities
                del_result = await db.execute(
                    delete(Liability).where(Liability.session_id.in_(session_ids))
                )
                result.liabilities = del_result.rowcount  # type: ignore[attr-defined]

                # 3d. Delete calculations
                del_result = await db.execute(
                    delete(DTICalculation).where(DTICalculation.session_id.in_(session_ids))
                )
                result.dti_calculations = del_result.rowcount  # type: ignore[attr-defined]

                del_result = await db.execute(
                    delete(CdQCalculation).where(CdQCalculation.session_id.in_(session_ids))
                )
                result.cdq_calculations = del_result.rowcount  # type: ignore[attr-defined]

                # 3e. Delete product matches
                del_result = await db.execute(
                    delete(ProductMatch).where(ProductMatch.session_id.in_(session_ids))
                )
                result.product_matches = del_result.rowcount  # type: ignore[attr-defined]

                # 3f. Delete quotation data
                del_result = await db.execute(
                    delete(QuotationData).where(QuotationData.session_id.in_(session_ids))
                )
                result.quotation_data = del_result.rowcount  # type: ignore[attr-defined]

                # 3g. Cancel pending/confirmed appointments
                upd_result = await db.execute(
                    update(Appointment)
                    .where(
                        Appointment.session_id.in_(session_ids),
                        Appointment.status.in_([
                            AppointmentStatus.PENDING.value,
                            AppointmentStatus.CONFIRMED.value,
                        ]),
                    )
                    .values(status=AppointmentStatus.CANCELLED.value)
                )
                result.appointments_cancelled = upd_result.rowcount  # type: ignore[attr-defined]

                # 3h. Redact messages
                upd_result = await db.execute(
                    update(Message)
                    .where(Message.session_id.in_(session_ids))
                    .values(content="[REDATTO]", media_url=None)
                )
                result.messages = upd_result.rowcount  # type: ignore[attr-defined]

                # 3i. Clear session classification fields
                await db.execute(
                    update(Session)
                    .where(Session.id.in_(session_ids))
                    .values(
                        employment_type=None,
                        employer_category=None,
                        pension_source=None,
                        track_type=None,
                        income_doc_type=None,
                    )
                )

            # 4. Anonymize user
            user = await db.get(User, user_id)
            if user is not None:
                user.first_name = "[REDATTO]"
                user.last_name = "[REDATTO]"
                user.email = None
                user.phone = None
                user.whatsapp_id = None
                user.telegram_id = f"deleted_{user.id}"
                user.codice_fiscale_encrypted = None
                user.consent_status = {}
                user.anonymized = True

            # 5. Mark request as completed
            request.status = DeletionRequestStatus.COMPLETED.value
            request.completed_at = datetime.now(UTC)
            await db.flush()

            result.success = True

            await emit(SystemEvent(
                event_type=EventType.DELETION_COMPLETED,
                user_id=user_id,
                data={
                    "deletion_request_id": str(deletion_request_id),
                    "sessions": result.sessions,
                    "messages": result.messages,
                    "documents": result.documents,
                },
                source_module="security.erasure",
            ))

            logger.info(
                "Erasure completed: user=%s sessions=%d messages=%d documents=%d",
                user_id,
                result.sessions,
                result.messages,
                result.documents,
            )

        except Exception as exc:
            result.error = str(exc)
            request.status = DeletionRequestStatus.FAILED.value
            await db.flush()
            logger.exception("Erasure failed: request=%s", deletion_request_id)

        return result


# Module-level singleton
erasure_processor = ErasureProcessor()
