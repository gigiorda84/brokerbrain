"""Admin web dashboard — FastAPI router with Jinja2 + HTMX.

Provides 6 pages and 2 HTMX partial endpoints for real-time updates.
All routes require HTTP Basic Auth via verify_admin dependency.
"""
# ruff: noqa: B008  — Depends() in function defaults is standard FastAPI

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import verify_admin
from src.admin.events import emit
from src.admin.formatters import (
    format_confidence,
    format_currency,
    format_date,
    format_datetime,
    format_duration_mins,
    format_percentage,
)
from src.admin.queries import (
    check_system_health,
    get_active_sessions,
    get_audit_log_paginated,
    get_gdpr_overview,
    get_recent_alerts,
    get_sessions_paginated,
    get_today_stats,
    resolve_session_id,
)
from src.db.engine import get_session
from src.schemas.events import EventType, SystemEvent
from src.security.encryption import field_encryptor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Jinja2 templates
_template_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))

# Register custom filters
templates.env.filters["currency"] = format_currency
templates.env.filters["date"] = format_date
templates.env.filters["datetime"] = format_datetime
templates.env.filters["percentage"] = format_percentage
templates.env.filters["duration"] = format_duration_mins
templates.env.filters["confidence"] = format_confidence


async def _emit_access(admin: str, page: str) -> None:
    """Emit ADMIN_ACCESS audit event for each page view."""
    await emit(SystemEvent(
        event_type=EventType.ADMIN_ACCESS,
        actor_id=admin,
        actor_role="admin",
        data={"page": page, "interface": "web"},
        source_module="admin.web",
    ))


def _page_range(current: int, total_pages: int) -> list[int]:
    """Generate a page number range for pagination."""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))
    if current <= 4:
        return list(range(1, 8))
    if current >= total_pages - 3:
        return list(range(total_pages - 6, total_pages + 1))
    return list(range(current - 3, current + 4))


# ── Full pages ───────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Dashboard — active sessions, today stats, recent alerts."""
    await _emit_access(admin, "dashboard")

    stats = await get_today_stats(db)
    active = await get_active_sessions(db)
    alerts = await get_recent_alerts(db)

    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats,
        "active_sessions": active,
        "alerts": alerts,
    })


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    page: int = Query(1, ge=1),
    outcome: str | None = Query(None),
    employment_type: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Paginated session list with filters."""
    await _emit_access(admin, "sessions")

    sessions, total = await get_sessions_paginated(
        db, page=page, outcome=outcome or None, employment_type=employment_type or None
    )
    per_page = 25
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "sessions.html", {
        "sessions": sessions,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "pages": _page_range(page, total_pages),
        "outcome": outcome or "",
        "employment_type": employment_type or "",
    })


@router.get("/session/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Full session detail with transcript."""
    await _emit_access(admin, "session_detail")

    session = await resolve_session_id(db, session_id)
    if session is None:
        return templates.TemplateResponse(request, "session_detail.html", {
            "session": None,
            "session_id": session_id,
            "fields": [],
            "messages": [],
        }, status_code=404)

    # Decrypt extracted data for display
    fields: list[dict[str, Any]] = []
    for ed in session.extracted_data:
        value = ed.value
        if ed.value_encrypted and value:
            try:
                value = field_encryptor.decrypt(value)
            except Exception:
                value = "[encrypted]"
        fields.append({
            "field_name": ed.field_name,
            "value": value,
            "source": ed.source,
            "confidence": ed.confidence,
        })

    # Sort messages by created_at for transcript
    messages = sorted(session.messages, key=lambda m: m.created_at)

    return templates.TemplateResponse(request, "session_detail.html", {
        "session": session,
        "session_id": session_id,
        "fields": fields,
        "messages": messages,
    })


@router.get("/health", response_class=HTMLResponse)
async def health_page(
    request: Request,
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """System health — Ollama, DB, Redis status."""
    await _emit_access(admin, "health")

    health = await check_system_health()

    return templates.TemplateResponse(request, "health.html", {
        "health": health,
    })


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    page: int = Query(1, ge=1),
    event_type: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Paginated audit log viewer."""
    await _emit_access(admin, "audit")

    logs, total = await get_audit_log_paginated(
        db, page=page, event_type=event_type or None
    )
    per_page = 50
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "audit.html", {
        "logs": logs,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "pages": _page_range(page, total_pages),
        "event_type": event_type or "",
    })


@router.get("/gdpr", response_class=HTMLResponse)
async def gdpr_page(
    request: Request,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """GDPR overview — pending deletions, consent stats."""
    await _emit_access(admin, "gdpr")

    gdpr = await get_gdpr_overview(db)

    return templates.TemplateResponse(request, "gdpr.html", {
        "gdpr": gdpr,
    })


# ── HTMX partials ────────────────────────────────────────────────────


@router.get("/partials/active", response_class=HTMLResponse)
async def partial_active_list(
    request: Request,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """HTMX partial — active sessions table (auto-refreshes every 10s)."""
    active = await get_active_sessions(db)
    return templates.TemplateResponse(request, "partials/active_list.html", {
        "active_sessions": active,
    })


@router.get("/partials/sessions", response_class=HTMLResponse)
async def partial_session_table(
    request: Request,
    page: int = Query(1, ge=1),
    outcome: str | None = Query(None),
    employment_type: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """HTMX partial — session table body for pagination."""
    sessions, total = await get_sessions_paginated(
        db, page=page, outcome=outcome or None, employment_type=employment_type or None
    )
    per_page = 25
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "partials/session_table.html", {
        "sessions": sessions,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "pages": _page_range(page, total_pages),
        "outcome": outcome or "",
        "employment_type": employment_type or "",
    })
