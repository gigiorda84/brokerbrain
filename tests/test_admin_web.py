"""Tests for the admin web dashboard.

Covers:
- HTTP Basic Auth (401 without creds, 401 wrong password, 200 correct)
- Dashboard, sessions, session detail, health, audit, GDPR pages
- Italian locale formatting functions
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.admin.formatters import (
    format_confidence,
    format_currency,
    format_date,
    format_datetime,
    format_duration_mins,
    format_percentage,
)

# ── Formatter unit tests ─────────────────────────────────────────────


class TestFormatCurrency:
    def test_integer(self):
        assert format_currency(1000) == "1.000,00"

    def test_decimal(self):
        assert format_currency(Decimal("1750.50")) == "1.750,50"

    def test_large(self):
        assert format_currency(Decimal("1234567.89")) == "1.234.567,89"

    def test_small(self):
        assert format_currency(Decimal("0.50")) == "0,50"

    def test_none(self):
        assert format_currency(None) == "-"

    def test_zero(self):
        assert format_currency(0) == "0,00"


class TestFormatDate:
    def test_date(self):
        dt = datetime(2026, 2, 16, 14, 30, tzinfo=UTC)
        assert format_date(dt) == "16/02/2026"

    def test_none(self):
        assert format_date(None) == "-"


class TestFormatDatetime:
    def test_datetime(self):
        dt = datetime(2026, 2, 16, 14, 30, tzinfo=UTC)
        assert format_datetime(dt) == "16/02/2026 14:30"

    def test_none(self):
        assert format_datetime(None) == "-"


class TestFormatPercentage:
    def test_ratio(self):
        assert format_percentage(0.243) == "24,3%"

    def test_zero(self):
        assert format_percentage(0.0) == "0,0%"

    def test_one(self):
        assert format_percentage(1.0) == "100,0%"

    def test_none(self):
        assert format_percentage(None) == "-"


class TestFormatDuration:
    def test_minutes_and_seconds(self):
        start = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 16, 14, 4, 32, tzinfo=UTC)
        assert format_duration_mins(start, end) == "4m 32s"

    def test_seconds_only(self):
        start = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 16, 14, 0, 45, tzinfo=UTC)
        assert format_duration_mins(start, end) == "45s"

    def test_none_start(self):
        assert format_duration_mins(None) == "-"


class TestFormatConfidence:
    def test_high(self):
        assert format_confidence(0.95) == "95%"

    def test_none(self):
        assert format_confidence(None) == "-"


# ── Web route integration tests ──────────────────────────────────────


def _make_auth_header(username: str = "admin", password: str = "testpass123") -> dict[str, str]:
    """Build HTTP Basic Auth header."""
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


@pytest.fixture
def mock_settings():
    """Patch settings to use test password."""
    with patch("src.admin.auth.settings") as mock:
        mock.security.admin_web_password = "testpass123"
        yield mock


@pytest.fixture
def mock_queries():
    """Patch all query functions used by web routes."""
    with (
        patch("src.admin.web.get_today_stats", new_callable=AsyncMock) as mock_stats,
        patch("src.admin.web.get_active_sessions", new_callable=AsyncMock) as mock_active,
        patch("src.admin.web.get_recent_alerts", new_callable=AsyncMock) as mock_alerts,
        patch("src.admin.web.get_sessions_paginated", new_callable=AsyncMock) as mock_paginated,
        patch("src.admin.web.resolve_session_id", new_callable=AsyncMock) as mock_resolve,
        patch("src.admin.web.check_system_health", new_callable=AsyncMock) as mock_health,
        patch("src.admin.web.get_audit_log_paginated", new_callable=AsyncMock) as mock_audit,
        patch("src.admin.web.get_gdpr_overview", new_callable=AsyncMock) as mock_gdpr,
        patch("src.admin.web.get_pending_leads_count", new_callable=AsyncMock) as mock_pending_leads,
        patch("src.admin.web.get_qualified_leads", new_callable=AsyncMock) as mock_qualified_leads,
        patch("src.admin.web.update_appointment_status", new_callable=AsyncMock) as mock_update_appt,
        patch("src.admin.web.emit", new_callable=AsyncMock),
    ):
        mock_stats.return_value = {
            "total": 10,
            "completed": 7,
            "qualified": 3,
            "abandoned": 2,
            "errors": 1,
            "qual_rate": 0.43,
            "state_counts": [],
        }
        mock_active.return_value = []
        mock_alerts.return_value = []
        mock_paginated.return_value = ([], 0)
        mock_resolve.return_value = None
        mock_health.return_value = {
            "llm": {
                "status": "ok",
                "provider": "Ollama",
                "latency_ms": 15,
                "conversation_model": "qwen3:8b",
                "vision_model": "qwen2.5-vl:7b",
                "loaded_models": ["qwen3:8b"],
            },
            "postgresql": {"status": "ok", "latency_ms": 2},
            "redis": {"status": "ok", "latency_ms": 1},
            "tokens": {
                "today": {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "all_time": {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        }
        mock_audit.return_value = ([], 0)
        mock_gdpr.return_value = {
            "pending_deletions": [],
            "total_users": 50,
            "with_consent": 45,
            "revoked": 3,
        }
        mock_pending_leads.return_value = 0
        mock_qualified_leads.return_value = ([], 0)
        mock_update_appt.return_value = None
        yield {
            "stats": mock_stats,
            "active": mock_active,
            "alerts": mock_alerts,
            "paginated": mock_paginated,
            "resolve": mock_resolve,
            "health": mock_health,
            "audit": mock_audit,
            "gdpr": mock_gdpr,
            "pending_leads": mock_pending_leads,
            "qualified_leads": mock_qualified_leads,
            "update_appt": mock_update_appt,
        }


@pytest.fixture
def mock_db():
    """Patch the DB session dependency."""
    mock_session = AsyncMock()
    with patch("src.admin.web.get_session") as mock_get:
        async def fake_get():
            yield mock_session
        mock_get.side_effect = fake_get
        yield mock_session


@pytest.fixture
def client(mock_settings, mock_queries, mock_db):
    """Create test client with all mocks in place."""
    from fastapi import FastAPI

    from src.admin.web import router

    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


class TestAuth:
    def test_401_without_credentials(self, client):
        resp = client.get("/admin/")
        assert resp.status_code == 401

    def test_401_wrong_password(self, client):
        resp = client.get("/admin/", headers=_make_auth_header(password="wrong"))
        assert resp.status_code == 401

    def test_200_correct_credentials(self, client):
        resp = client.get("/admin/", headers=_make_auth_header())
        assert resp.status_code == 200


class TestDashboard:
    def test_renders(self, client):
        resp = client.get("/admin/", headers=_make_auth_header())
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    def test_contains_stats(self, client):
        resp = client.get("/admin/", headers=_make_auth_header())
        assert "Sessioni oggi" in resp.text
        assert "Completate" in resp.text
        assert "Qualificate" in resp.text


class TestSessionsList:
    def test_renders(self, client):
        resp = client.get("/admin/sessions", headers=_make_auth_header())
        assert resp.status_code == 200
        assert "Sessioni" in resp.text

    def test_filters_present(self, client):
        resp = client.get("/admin/sessions", headers=_make_auth_header())
        assert "Esito" in resp.text
        assert "Tipo impiego" in resp.text


class TestSessionDetail:
    def test_404_missing_session(self, client):
        resp = client.get("/admin/session/abc12345", headers=_make_auth_header())
        assert resp.status_code == 404
        assert "non trovata" in resp.text

    def test_renders_with_session(self, client, mock_queries):
        session_mock = _make_session_mock()
        mock_queries["resolve"].return_value = session_mock

        resp = client.get("/admin/session/abc12345", headers=_make_auth_header())
        assert resp.status_code == 200
        assert "Dati raccolti" in resp.text


class TestHealth:
    def test_renders(self, client):
        resp = client.get("/admin/health", headers=_make_auth_header())
        assert resp.status_code == 200
        assert "Ollama" in resp.text
        assert "PostgreSQL" in resp.text
        assert "Redis" in resp.text
        assert "OK" in resp.text


class TestAudit:
    def test_renders(self, client):
        resp = client.get("/admin/audit", headers=_make_auth_header())
        assert resp.status_code == 200
        assert "Log Audit" in resp.text


class TestGDPR:
    def test_renders(self, client):
        resp = client.get("/admin/gdpr", headers=_make_auth_header())
        assert resp.status_code == 200
        assert "GDPR" in resp.text
        assert "50" in resp.text  # total_users
        assert "45" in resp.text  # with_consent


# ── Helpers ──────────────────────────────────────────────────────────


def _make_session_mock():
    """Build a mock Session with relationships for detail view."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.id = uuid.uuid4()
    session.current_state = "employment_type"
    session.outcome = None
    session.employment_type = "dipendente"
    session.employer_category = "privato"
    session.pension_source = None
    session.track_type = "manual"
    session.started_at = datetime.now(UTC) - timedelta(minutes=5)
    session.completed_at = None
    session.message_count = 8
    session.user = MagicMock()
    session.user.first_name = "Mario"
    session.extracted_data = []
    session.liabilities = []
    session.dti_calculations = []
    session.cdq_calculations = []
    session.product_matches = []
    session.documents = []
    session.messages = []
    session.appointments = []
    return session
