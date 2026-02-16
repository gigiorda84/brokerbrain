"""Shared database query functions for admin web dashboard and admin bot.

Extracted from bot.py patterns so both Telegram bot and web dashboard
can reuse the same query logic.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.expression import cast

from src.config import settings
from src.db.engine import async_session_factory, redis_client
from src.models.audit import AuditLog
from src.models.consent import ConsentRecord
from src.models.deletion import DataDeletionRequest
from src.models.session import Session
from src.models.user import User

logger = logging.getLogger(__name__)


async def get_active_sessions(db: AsyncSession, limit: int = 20) -> list[Session]:
    """Get sessions where outcome IS NULL (still in progress), most recent first."""
    result = await db.execute(
        select(Session)
        .where(Session.outcome.is_(None))
        .options(selectinload(Session.user))
        .order_by(Session.started_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_today_stats(db: AsyncSession) -> dict[str, Any]:
    """Get today's session statistics.

    Returns dict with: total, completed, qualified, abandoned, errors,
    qual_rate, state_counts.
    """
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # Total sessions today
    result = await db.execute(
        select(func.count(Session.id)).where(Session.started_at >= today_start)
    )
    total = result.scalar() or 0

    # Completed
    result = await db.execute(
        select(func.count(Session.id)).where(
            Session.started_at >= today_start,
            Session.outcome.isnot(None),
        )
    )
    completed = result.scalar() or 0

    # Qualified
    result = await db.execute(
        select(func.count(Session.id)).where(
            Session.started_at >= today_start,
            Session.outcome == "qualified",
        )
    )
    qualified = result.scalar() or 0

    # Abandoned
    result = await db.execute(
        select(func.count(Session.id)).where(
            Session.started_at >= today_start,
            Session.outcome == "abandoned",
        )
    )
    abandoned = result.scalar() or 0

    # Errors today
    result = await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.created_at >= today_start,
            AuditLog.event_type.like("%error%"),
        )
    )
    errors = result.scalar() or 0

    # Active sessions by state
    result = await db.execute(
        select(Session.current_state, func.count(Session.id))
        .where(Session.outcome.is_(None))
        .group_by(Session.current_state)
    )
    state_counts = result.all()

    qual_rate = qualified / completed if completed > 0 else 0.0

    return {
        "total": total,
        "completed": completed,
        "qualified": qualified,
        "abandoned": abandoned,
        "errors": errors,
        "qual_rate": qual_rate,
        "state_counts": state_counts,
    }


async def get_recent_alerts(db: AsyncSession, limit: int = 10) -> list[AuditLog]:
    """Get recent alert-like audit events (errors, escalations, alerts)."""
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.event_type.like("%error%")
            | AuditLog.event_type.like("%alert%")
            | AuditLog.event_type.like("%escalat%")
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_sessions_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 25,
    outcome: str | None = None,
    employment_type: str | None = None,
) -> tuple[list[Session], int]:
    """Get paginated session list with optional filters.

    Returns (sessions, total_count).
    """
    query = select(Session).options(selectinload(Session.user))
    count_query = select(func.count(Session.id))

    if outcome:
        query = query.where(Session.outcome == outcome)
        count_query = count_query.where(Session.outcome == outcome)
    if employment_type:
        query = query.where(Session.employment_type == employment_type)
        count_query = count_query.where(Session.employment_type == employment_type)

    # Total count
    result = await db.execute(count_query)
    total = result.scalar() or 0

    # Paginated results
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(Session.started_at.desc()).offset(offset).limit(per_page)
    )
    sessions = list(result.scalars().all())

    return sessions, total


async def get_session_full(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    """Load a session with ALL relationships for detail view."""
    result = await db.execute(
        select(Session)
        .where(Session.id == session_id)
        .options(
            selectinload(Session.user),
            selectinload(Session.extracted_data),
            selectinload(Session.liabilities),
            selectinload(Session.dti_calculations),
            selectinload(Session.cdq_calculations),
            selectinload(Session.product_matches),
            selectinload(Session.documents),
            selectinload(Session.messages),
        )
    )
    return result.scalar_one_or_none()


async def resolve_session_id(db: AsyncSession, id_str: str) -> Session | None:
    """Resolve a session by short UUID prefix or full UUID.

    Supports 8-char prefix (e.g., "a1b2c3d4") or full 36-char UUID.
    """
    if len(id_str) < 36:
        result = await db.execute(
            select(Session)
            .where(cast(Session.id, String).like(f"{id_str}%"))
            .options(
                selectinload(Session.user),
                selectinload(Session.extracted_data),
                selectinload(Session.liabilities),
                selectinload(Session.dti_calculations),
                selectinload(Session.cdq_calculations),
                selectinload(Session.product_matches),
                selectinload(Session.documents),
                selectinload(Session.messages),
            )
        )
    else:
        result = await db.execute(
            select(Session)
            .where(Session.id == uuid.UUID(id_str))
            .options(
                selectinload(Session.user),
                selectinload(Session.extracted_data),
                selectinload(Session.liabilities),
                selectinload(Session.dti_calculations),
                selectinload(Session.cdq_calculations),
                selectinload(Session.product_matches),
                selectinload(Session.documents),
                selectinload(Session.messages),
            )
        )
    return result.scalars().first()


async def get_audit_log_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 50,
    event_type: str | None = None,
) -> tuple[list[AuditLog], int]:
    """Get paginated audit log with optional event_type filter."""
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if event_type:
        query = query.where(AuditLog.event_type == event_type)
        count_query = count_query.where(AuditLog.event_type == event_type)

    result = await db.execute(count_query)
    total = result.scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(AuditLog.created_at.desc()).offset(offset).limit(per_page)
    )
    logs = list(result.scalars().all())

    return logs, total


async def get_gdpr_overview(db: AsyncSession) -> dict[str, Any]:
    """Get GDPR overview: pending deletions, consent stats."""
    # Pending deletion requests
    result = await db.execute(
        select(DataDeletionRequest)
        .options(selectinload(DataDeletionRequest.user))
        .where(DataDeletionRequest.status.in_(["pending", "in_progress"]))
        .order_by(DataDeletionRequest.requested_at.desc())
    )
    pending_deletions = list(result.scalars().all())

    # Consent stats
    result = await db.execute(select(func.count(User.id)).where(User.anonymized.is_(False)))
    total_users = result.scalar() or 0

    result = await db.execute(
        select(func.count(func.distinct(ConsentRecord.user_id))).where(
            ConsentRecord.granted.is_(True)
        )
    )
    with_consent = result.scalar() or 0

    result = await db.execute(
        select(func.count(func.distinct(ConsentRecord.user_id))).where(
            ConsentRecord.granted.is_(False)
        )
    )
    revoked = result.scalar() or 0

    return {
        "pending_deletions": pending_deletions,
        "total_users": total_users,
        "with_consent": with_consent,
        "revoked": revoked,
    }


async def check_system_health() -> dict[str, Any]:
    """Check Ollama, PostgreSQL, and Redis health with latency measurements."""
    health: dict[str, Any] = {}

    # Ollama
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.llm.ollama_base_url}/api/tags")
            resp.raise_for_status()
        ms = int((time.monotonic() - t0) * 1000)
        models = resp.json().get("models", [])
        model_names = [m.get("name", "?") for m in models]
        health["ollama"] = {"status": "ok", "latency_ms": ms, "models": model_names}
    except Exception as exc:
        health["ollama"] = {"status": "error", "error": str(exc)}

    # PostgreSQL
    try:
        t0 = time.monotonic()
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
        ms = int((time.monotonic() - t0) * 1000)
        health["postgresql"] = {"status": "ok", "latency_ms": ms}
    except Exception as exc:
        health["postgresql"] = {"status": "error", "error": str(exc)}

    # Redis
    try:
        t0 = time.monotonic()
        await redis_client.ping()
        ms = int((time.monotonic() - t0) * 1000)
        health["redis"] = {"status": "ok", "latency_ms": ms}
    except Exception as exc:
        health["redis"] = {"status": "error", "error": str(exc)}

    return health
