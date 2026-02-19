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
from src.models.document import Document
from src.models.product_match import ProductMatch
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


async def resolve_deletion_request(db: AsyncSession, id_str: str) -> DataDeletionRequest | None:
    """Find a DataDeletionRequest by full UUID or short prefix."""
    if len(id_str) < 36:
        result = await db.execute(
            select(DataDeletionRequest)
            .where(cast(DataDeletionRequest.id, String).like(f"{id_str}%"))
            .options(selectinload(DataDeletionRequest.user))
        )
    else:
        result = await db.execute(
            select(DataDeletionRequest)
            .where(DataDeletionRequest.id == uuid.UUID(id_str))
            .options(selectinload(DataDeletionRequest.user))
        )
    return result.scalars().first()


async def check_system_health() -> dict[str, Any]:
    """Check LLM provider, PostgreSQL, and Redis health with latency measurements."""
    health: dict[str, Any] = {}

    provider = settings.llm.llm_provider  # "deepinfra" or "ollama"

    # LLM provider
    if provider == "deepinfra":
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{settings.llm.deepinfra_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.llm.deepinfra_api_key}"},
                )
                resp.raise_for_status()
            ms = int((time.monotonic() - t0) * 1000)
            health["llm"] = {
                "status": "ok",
                "provider": "DeepInfra",
                "latency_ms": ms,
                "conversation_model": settings.llm.conversation_model,
                "vision_model": settings.llm.vision_model,
            }
        except Exception as exc:
            health["llm"] = {
                "status": "error",
                "provider": "DeepInfra",
                "conversation_model": settings.llm.conversation_model,
                "vision_model": settings.llm.vision_model,
                "error": str(exc),
            }
    else:
        # Ollama
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.llm.ollama_base_url}/api/tags")
                resp.raise_for_status()
            ms = int((time.monotonic() - t0) * 1000)
            models = resp.json().get("models", [])
            loaded = [m.get("name", "?") for m in models]
            health["llm"] = {
                "status": "ok",
                "provider": "Ollama",
                "latency_ms": ms,
                "conversation_model": settings.llm.conversation_model,
                "vision_model": settings.llm.vision_model,
                "loaded_models": loaded,
            }
        except Exception as exc:
            health["llm"] = {
                "status": "error",
                "provider": "Ollama",
                "conversation_model": settings.llm.conversation_model,
                "vision_model": settings.llm.vision_model,
                "error": str(exc),
            }

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

    # Token usage (from audit_log)
    health["tokens"] = await get_token_usage()

    return health


async def get_token_usage() -> dict[str, Any]:
    """Aggregate token usage from LLM_RESPONSE audit log entries."""
    try:
        async with async_session_factory() as db:
            # Total tokens (all time)
            result = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS request_count,
                        COALESCE(SUM((data->>'prompt_tokens')::int), 0) AS total_prompt,
                        COALESCE(SUM((data->>'completion_tokens')::int), 0) AS total_completion
                    FROM audit_log
                    WHERE event_type = 'llm.response'
                """)
            )
            totals = result.mappings().first()

            # Today's tokens
            result_today = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS request_count,
                        COALESCE(SUM((data->>'prompt_tokens')::int), 0) AS total_prompt,
                        COALESCE(SUM((data->>'completion_tokens')::int), 0) AS total_completion
                    FROM audit_log
                    WHERE event_type = 'llm.response'
                      AND created_at >= CURRENT_DATE
                """)
            )
            today = result_today.mappings().first()

        return {
            "all_time": {
                "requests": totals["request_count"] if totals else 0,
                "prompt_tokens": totals["total_prompt"] if totals else 0,
                "completion_tokens": totals["total_completion"] if totals else 0,
                "total_tokens": (totals["total_prompt"] + totals["total_completion"]) if totals else 0,
            },
            "today": {
                "requests": today["request_count"] if today else 0,
                "prompt_tokens": today["total_prompt"] if today else 0,
                "completion_tokens": today["total_completion"] if today else 0,
                "total_tokens": (today["total_prompt"] + today["total_completion"]) if today else 0,
            },
        }
    except Exception:
        logging.getLogger(__name__).warning("Failed to query token usage", exc_info=True)
        return {
            "all_time": {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "today": {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


# ── Analytics queries ─────────────────────────────────────────────────


async def get_daily_volume(db: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    """Sessions per day grouped by outcome for the last N days.

    Returns list of {date, outcome, count} dicts.
    """
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date(Session.started_at).label("day"),
            func.coalesce(Session.outcome, "in_corso").label("outcome"),
            func.count(Session.id).label("cnt"),
        )
        .where(Session.started_at >= cutoff)
        .group_by("day", "outcome")
        .order_by("day")
    )
    return [{"date": str(row.day), "outcome": row.outcome, "count": row.cnt} for row in result.all()]


async def get_conversion_funnel(db: AsyncSession) -> list[dict[str, Any]]:
    """Count sessions at each funnel stage.

    Returns list of {stage, count} ordered top-to-bottom.
    """
    stages = [
        ("Avviata", select(func.count(Session.id))),
        ("Consenso", select(func.count(Session.id)).where(
            Session.current_state.notin_(["welcome", "consent"])
            | Session.outcome.isnot(None)
        )),
        ("Tipo impiego", select(func.count(Session.id)).where(
            Session.employment_type.isnot(None)
        )),
        ("Documenti", select(func.count(Session.id)).where(
            Session.track_type.isnot(None)
        )),
        ("Calcolo DTI", select(func.count(Session.id)).where(
            Session.current_state.in_(["result", "scheduling", "completed"])
            | Session.outcome.in_(["qualified", "not_qualified"])
        )),
        ("Qualificata", select(func.count(Session.id)).where(
            Session.outcome == "qualified"
        )),
    ]
    funnel: list[dict[str, Any]] = []
    for stage_name, query in stages:
        result = await db.execute(query)
        funnel.append({"stage": stage_name, "count": result.scalar() or 0})
    return funnel


async def get_product_distribution(db: AsyncSession) -> list[dict[str, Any]]:
    """Count eligible ProductMatch records grouped by product_name."""
    result = await db.execute(
        select(
            ProductMatch.product_name,
            func.count(ProductMatch.id).label("cnt"),
        )
        .where(ProductMatch.eligible.is_(True))
        .group_by(ProductMatch.product_name)
        .order_by(func.count(ProductMatch.id).desc())
    )
    return [{"product": row.product_name, "count": row.cnt} for row in result.all()]


async def get_dti_histogram(db: AsyncSession) -> list[dict[str, Any]]:
    """DTI values bucketed into ranges for histogram display.

    Reads from the JSONB data of DTI_CALCULATED audit events.
    Returns list of {bucket, count}.
    """
    from src.models.calculation import DTICalculation

    result = await db.execute(
        select(DTICalculation.current_dti).where(DTICalculation.current_dti.isnot(None))
    )
    dti_values = [float(row[0]) for row in result.all()]

    buckets = ["0-10%", "10-20%", "20-30%", "30-40%", "40-50%", "50%+"]
    counts = [0] * 6
    for v in dti_values:
        pct = v * 100
        if pct < 10:
            counts[0] += 1
        elif pct < 20:
            counts[1] += 1
        elif pct < 30:
            counts[2] += 1
        elif pct < 40:
            counts[3] += 1
        elif pct < 50:
            counts[4] += 1
        else:
            counts[5] += 1

    return [{"bucket": b, "count": c} for b, c in zip(buckets, counts, strict=True)]


# ── Pipeline + debug queries ──────────────────────────────────────────


async def get_session_pipeline(db: AsyncSession, session_id: uuid.UUID) -> list[AuditLog]:
    """Get processing-relevant audit events for a session, ordered chronologically."""
    relevant_prefixes = (
        "session.started", "message.", "document.", "ocr.", "data.",
        "calculation.", "eligibility.", "llm.",
    )
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.session_id == session_id,
            func.substr(AuditLog.event_type, 1, 4).in_(
                [p[:4] for p in relevant_prefixes]
            ),
        )
        .order_by(AuditLog.created_at.asc())
    )
    logs = list(result.scalars().all())
    # Filter more precisely in Python (SQL prefix matching is coarse)
    return [
        log for log in logs
        if any(log.event_type.startswith(p.rstrip(".")) for p in relevant_prefixes)
    ]


async def get_session_llm_events(db: AsyncSession, session_id: uuid.UUID) -> list[AuditLog]:
    """Get LLM request/response/error audit events for a session."""
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.session_id == session_id,
            AuditLog.event_type.in_(["llm.request", "llm.response", "llm.error"]),
        )
        .order_by(AuditLog.created_at.asc())
    )
    return list(result.scalars().all())


async def get_document_detail(
    db: AsyncSession, document_id: uuid.UUID
) -> Document | None:
    """Load a single Document with its parent session for breadcrumb."""
    from sqlalchemy.orm import selectinload as _sel

    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .options(_sel(Document.session))
    )
    return result.scalar_one_or_none()
