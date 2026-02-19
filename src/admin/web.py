"""Admin web dashboard — FastAPI router with Jinja2 + HTMX.

Provides 12 pages, 3 HTMX partial endpoints, and 1 JSON API for analytics.
All routes require HTTP Basic Auth via verify_admin dependency.
"""
# ruff: noqa: B008  — Depends() in function defaults is standard FastAPI

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    get_conversion_funnel,
    get_daily_volume,
    get_document_detail,
    get_dti_histogram,
    get_gdpr_overview,
    get_pending_leads_count,
    get_product_distribution,
    get_qualified_leads,
    get_recent_alerts,
    get_session_llm_events,
    get_session_pipeline,
    get_sessions_paginated,
    get_today_stats,
    resolve_deletion_request,
    resolve_session_id,
    update_appointment_status,
)
from src.db.engine import get_session
from src.schemas.events import EventType, SystemEvent
from src.security.encryption import field_encryptor
from src.security.erasure import erasure_processor

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
    pending_leads = await get_pending_leads_count(db)
    recent_leads, _ = await get_qualified_leads(db, page=1, per_page=5)

    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats,
        "active_sessions": active,
        "alerts": alerts,
        "pending_leads": pending_leads,
        "recent_leads": recent_leads,
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


@router.get("/leads", response_class=HTMLResponse)
async def leads_page(
    request: Request,
    page: int = Query(1, ge=1),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Qualified leads list with appointment status."""
    await _emit_access(admin, "leads")

    leads, total = await get_qualified_leads(
        db, page=page, appointment_status=status or None
    )
    per_page = 25
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "leads.html", {
        "leads": leads,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "pages": _page_range(page, total_pages),
        "status": status or "",
    })


@router.post("/leads/{appointment_id}/status", response_class=HTMLResponse)
async def update_lead_status(
    request: Request,
    appointment_id: str,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """HTMX endpoint — update appointment status, return badge HTML."""
    await _emit_access(admin, "lead_status_update")

    form = await request.form()
    new_status = str(form.get("status", ""))

    valid_statuses = {"pending", "confirmed", "contacted", "completed", "no_show", "cancelled"}
    if new_status not in valid_statuses:
        return HTMLResponse(
            '<span class="text-red-600 text-sm">Stato non valido</span>',
            status_code=400,
        )

    try:
        appt_uuid = uuid.UUID(appointment_id)
    except ValueError:
        return HTMLResponse(
            '<span class="text-red-600 text-sm">ID non valido</span>',
            status_code=400,
        )

    appointment = await update_appointment_status(db, appt_uuid, new_status)
    if appointment is None:
        return HTMLResponse(
            '<span class="text-red-600 text-sm">Appuntamento non trovato</span>',
            status_code=404,
        )

    await db.commit()

    status_colors = {
        "pending": "bg-yellow-100 text-yellow-800",
        "confirmed": "bg-blue-100 text-blue-800",
        "contacted": "bg-indigo-100 text-indigo-800",
        "completed": "bg-green-100 text-green-800",
        "no_show": "bg-red-100 text-red-800",
        "cancelled": "bg-gray-100 text-gray-800",
    }
    color = status_colors.get(new_status, "bg-gray-100 text-gray-800")

    return HTMLResponse(
        f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full '
        f'text-xs font-medium {color}">{new_status}</span>'
    )


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
    """System health — LLM provider, DB, Redis status + token usage."""
    await _emit_access(admin, "health")

    health = await check_system_health()

    # Server uptime
    from datetime import datetime, timezone

    started_at: datetime | None = getattr(request.app.state, "started_at", None)
    if started_at:
        delta = datetime.now(timezone.utc) - started_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            uptime_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            uptime_str = f"{minutes}m {seconds}s"
        else:
            uptime_str = f"{seconds}s"
    else:
        uptime_str = "n/d"

    return templates.TemplateResponse(request, "health.html", {
        "health": health,
        "server_uptime": uptime_str,
        "server_started_at": started_at.strftime("%d/%m/%Y %H:%M:%S UTC") if started_at else "n/d",
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


# ── Analytics ─────────────────────────────────────────────────────────


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Analytics dashboard with Chart.js charts."""
    await _emit_access(admin, "analytics")

    daily = await get_daily_volume(db)
    funnel = await get_conversion_funnel(db)
    products = await get_product_distribution(db)
    dti = await get_dti_histogram(db)

    return templates.TemplateResponse(request, "analytics.html", {
        "daily": daily,
        "funnel": funnel,
        "products": products,
        "dti": dti,
    })


@router.get("/api/analytics")
async def analytics_api(
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> JSONResponse:
    """JSON endpoint returning all analytics datasets for chart refresh."""
    daily = await get_daily_volume(db)
    funnel = await get_conversion_funnel(db)
    products = await get_product_distribution(db)
    dti = await get_dti_histogram(db)

    return JSONResponse({
        "daily_volume": daily,
        "conversion_funnel": funnel,
        "product_distribution": products,
        "dti_histogram": dti,
    })


# ── Pipeline ──────────────────────────────────────────────────────────


@router.get("/pipeline/{session_id}", response_class=HTMLResponse)
async def pipeline_page(
    request: Request,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Visual processing pipeline timeline for a session."""
    await _emit_access(admin, "pipeline")

    session = await resolve_session_id(db, session_id)
    if session is None:
        return templates.TemplateResponse(request, "pipeline.html", {
            "session": None,
            "session_id": session_id,
            "events": [],
        }, status_code=404)

    events = await get_session_pipeline(db, session.id)

    return templates.TemplateResponse(request, "pipeline.html", {
        "session": session,
        "session_id": session_id,
        "events": events,
    })


# ── Raw LLM debug ────────────────────────────────────────────────────


@router.get("/session/{session_id}/raw", response_class=HTMLResponse)
async def session_raw_page(
    request: Request,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Raw LLM prompts/responses debug view for a session."""
    await _emit_access(admin, "session_raw")

    session = await resolve_session_id(db, session_id)
    if session is None:
        return templates.TemplateResponse(request, "session_raw.html", {
            "session": None,
            "session_id": session_id,
            "llm_events": [],
        }, status_code=404)

    llm_events = await get_session_llm_events(db, session.id)

    return templates.TemplateResponse(request, "session_raw.html", {
        "session": session,
        "session_id": session_id,
        "llm_events": llm_events,
    })


# ── Document detail ───────────────────────────────────────────────────


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def document_detail_page(
    request: Request,
    document_id: str,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Single document OCR results viewer."""
    await _emit_access(admin, "document_detail")

    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        return templates.TemplateResponse(request, "document_detail.html", {
            "document": None,
            "document_id": document_id,
        }, status_code=404)

    document = await get_document_detail(db, doc_uuid)

    return templates.TemplateResponse(request, "document_detail.html", {
        "document": document,
        "document_id": document_id,
    })


# ── Eligibility rules viewer ─────────────────────────────────────────


# Static display data for the 9 products and their rule conditions.
# Built from inspecting the rule functions in src/eligibility/rules.py.
RULES_DISPLAY: list[dict[str, Any]] = [
    {
        "product": "Cessione del Quinto Stipendio",
        "sub_types": "Statale, Pubblico, Parapubblico, Privato",
        "conditions": [
            {"name": "Tipo impiego", "desc": "Lavoratore dipendente", "hard": True},
            {"name": "Categoria datore", "desc": "Categoria datore di lavoro specificata", "hard": True},
            {"name": "Capacità CdQ", "desc": "Capacità residua CdQ > 0 (1/5 stipendio netto)", "hard": True},
            {"name": "Dimensione azienda", "desc": "Per privati: almeno 16 dipendenti", "hard": False},
        ],
    },
    {
        "product": "Cessione del Quinto Pensione",
        "sub_types": "INPS, INPDAP, Altro ente",
        "conditions": [
            {"name": "Tipo impiego", "desc": "Pensionato", "hard": True},
            {"name": "Cassa pensionistica", "desc": "Cassa pensionistica specificata", "hard": True},
            {"name": "Capacità CdQ", "desc": "Capacità residua CdQ > 0 (1/5 pensione netta)", "hard": True},
            {"name": "Età massima", "desc": "Età compatibile con durata minima (max 85 a fine piano)", "hard": True},
        ],
    },
    {
        "product": "Delegazione di Pagamento",
        "sub_types": "Statale, Pubblico, Parapubblico, Privato",
        "conditions": [
            {"name": "Tipo impiego", "desc": "Lavoratore dipendente", "hard": True},
            {"name": "Categoria datore", "desc": "Categoria datore di lavoro specificata", "hard": True},
            {"name": "Capacità delega", "desc": "Capacità residua delega > 0 (1/5 stipendio netto)", "hard": True},
            {"name": "Datore accetta delega", "desc": "Il datore di lavoro accetta la delegazione", "hard": False},
        ],
    },
    {
        "product": "Prestito Personale",
        "sub_types": None,
        "conditions": [
            {"name": "Reddito minimo", "desc": "Reddito netto mensile >= €800", "hard": True},
            {"name": "DTI", "desc": "Rapporto debiti/reddito <= 40%", "hard": True},
            {"name": "Garante", "desc": "Per disoccupati: garante consigliato", "hard": False},
        ],
    },
    {
        "product": "Mutuo Acquisto",
        "sub_types": None,
        "conditions": [
            {"name": "Reddito minimo", "desc": "Reddito netto mensile >= €1.000", "hard": True},
            {"name": "DTI", "desc": "Rapporto debiti/reddito <= 35%", "hard": True},
            {"name": "Tipo impiego", "desc": "Non disoccupato", "hard": True},
        ],
    },
    {
        "product": "Mutuo Surroga",
        "sub_types": None,
        "conditions": [
            {"name": "Mutuo in corso", "desc": "Deve avere un mutuo esistente", "hard": True},
            {"name": "Reddito minimo", "desc": "Reddito netto mensile >= €1.000", "hard": True},
            {"name": "Tipo impiego", "desc": "Non disoccupato", "hard": True},
        ],
    },
    {
        "product": "Mutuo Consolidamento Debiti",
        "sub_types": None,
        "conditions": [
            {"name": "Debiti multipli", "desc": "Almeno 2 finanziamenti in corso", "hard": True},
            {"name": "DTI alto", "desc": "Rapporto debiti/reddito > 30% (altrimenti non conviene)", "hard": True},
            {"name": "Tipo impiego", "desc": "Non disoccupato", "hard": True},
        ],
    },
    {
        "product": "Anticipo TFS/TFR",
        "sub_types": None,
        "conditions": [
            {"name": "Tipo impiego", "desc": "Pensionato", "hard": True},
            {"name": "Ex dipendente pubblico", "desc": "Deve essere ex dipendente pubblico", "hard": True},
        ],
    },
    {
        "product": "Credito Assicurativo",
        "sub_types": None,
        "conditions": [
            {"name": "Tipo impiego", "desc": "Non disoccupato", "hard": True},
            {"name": "Altri prodotti", "desc": "Idoneo per almeno un altro prodotto", "hard": True},
        ],
    },
]


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(
    request: Request,
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Read-only view of all 9 product eligibility rules."""
    await _emit_access(admin, "rules")

    return templates.TemplateResponse(request, "rules.html", {
        "rules": RULES_DISPLAY,
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


# ── GDPR actions ────────────────────────────────────────────────────


@router.post("/gdpr/process/{request_id}", response_class=HTMLResponse)
async def gdpr_process_request(
    request: Request,
    request_id: str,
    db: AsyncSession = Depends(get_session),
    admin: str = Depends(verify_admin),
) -> HTMLResponse:
    """Process a deletion request — returns HTMX partial with result."""
    await _emit_access(admin, "gdpr_process")

    deletion_req = await resolve_deletion_request(db, request_id)
    if deletion_req is None:
        return HTMLResponse(
            '<span class="text-red-600 text-sm">Richiesta non trovata</span>',
            status_code=404,
        )

    result = await erasure_processor.process_erasure(db, deletion_req.id)

    if result.success:
        return HTMLResponse(
            '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full '
            'text-xs font-medium bg-green-100 text-green-800">'
            f"Completata ({result.sessions} sessioni, {result.messages} messaggi)</span>"
        )

    return HTMLResponse(
        '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full '
        f'text-xs font-medium bg-red-100 text-red-800">Errore: {result.error}</span>'
    )
