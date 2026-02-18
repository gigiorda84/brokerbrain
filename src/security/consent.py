"""Consent management — records, checks, and exports GDPR consent.

Every consent grant/revocation creates an immutable ConsentRecord row.
The User.consent_status JSONB is updated as a cache but ConsentRecord
is the authoritative source.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.events import emit
from src.models.consent import ConsentRecord
from src.models.enums import ConsentType
from src.models.user import User
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)

# Maps LLM field names (from consent prompt action data) to ConsentType enums
CONSENT_FIELD_MAP: dict[str, ConsentType] = {
    "consent_privacy": ConsentType.PRIVACY_POLICY,
    "consent_sensitive": ConsentType.DATA_PROCESSING,
}

# Both mandatory consents required before data processing
REQUIRED_CONSENTS: frozenset[ConsentType] = frozenset({
    ConsentType.PRIVACY_POLICY,
    ConsentType.DATA_PROCESSING,
})


class ConsentManager:
    """Stateless consent operations — AsyncSession passed per call."""

    async def record_consent(
        self,
        db: AsyncSession,
        user_id: Any,
        consent_type: ConsentType,
        granted: bool,
        method: str = "chat",
        message_text: str | None = None,
    ) -> ConsentRecord:
        """Create an immutable ConsentRecord and update the User JSONB cache."""
        record = ConsentRecord(
            user_id=user_id,
            consent_type=consent_type.value,
            granted=granted,
            method=method,
            message_text=message_text,
        )
        db.add(record)

        # Update JSONB cache on User
        user = await db.get(User, user_id)
        if user is not None:
            status = dict(user.consent_status or {})
            status[consent_type.value] = granted
            user.consent_status = status

        await db.flush()

        event_type = EventType.CONSENT_GRANTED if granted else EventType.CONSENT_REVOKED
        await emit(SystemEvent(
            event_type=event_type,
            user_id=user_id,
            data={
                "consent_type": consent_type.value,
                "granted": granted,
                "method": method,
            },
            source_module="security.consent",
        ))

        logger.info(
            "Consent %s: user=%s type=%s method=%s",
            "granted" if granted else "revoked",
            user_id,
            consent_type.value,
            method,
        )
        return record

    async def check_required_consent(self, db: AsyncSession, user_id: Any) -> bool:
        """Return True if the user has granted all required consents.

        Checks the latest ConsentRecord per required type (authoritative source).
        """
        for consent_type in REQUIRED_CONSENTS:
            result = await db.execute(
                select(ConsentRecord)
                .where(
                    ConsentRecord.user_id == user_id,
                    ConsentRecord.consent_type == consent_type.value,
                )
                .order_by(ConsentRecord.created_at.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            if latest is None or not latest.granted:
                return False
        return True

    async def get_consent_status(self, db: AsyncSession, user_id: Any) -> dict[str, bool]:
        """Return current consent status for all 4 types from latest records."""
        status: dict[str, bool] = {}
        for consent_type in ConsentType:
            result = await db.execute(
                select(ConsentRecord)
                .where(
                    ConsentRecord.user_id == user_id,
                    ConsentRecord.consent_type == consent_type.value,
                )
                .order_by(ConsentRecord.created_at.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            status[consent_type.value] = latest.granted if latest is not None else False
        return status

    async def revoke_all(
        self,
        db: AsyncSession,
        user_id: Any,
        method: str = "erasure",
    ) -> list[ConsentRecord]:
        """Revoke all currently-granted consents. Skips already-revoked types."""
        current = await self.get_consent_status(db, user_id)
        records: list[ConsentRecord] = []

        for type_value, granted in current.items():
            if granted:
                record = await self.record_consent(
                    db,
                    user_id,
                    ConsentType(type_value),
                    granted=False,
                    method=method,
                )
                records.append(record)

        return records

    async def export_consent_history(self, db: AsyncSession, user_id: Any) -> list[dict[str, Any]]:
        """Return the full consent trail for /i_miei_dati."""
        result = await db.execute(
            select(ConsentRecord)
            .where(ConsentRecord.user_id == user_id)
            .order_by(ConsentRecord.created_at.asc())
        )
        records = result.scalars().all()

        return [
            {
                "consent_type": r.consent_type,
                "granted": r.granted,
                "method": r.method,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]


# Module-level singleton
consent_manager = ConsentManager()
