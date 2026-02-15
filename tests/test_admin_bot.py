"""Tests for admin bot, alert engine, and audit subscriber.

Covers:
- Authorization (admin_only decorator)
- All 9 core commands (mocked DB + services)
- Alert engine rule evaluation
- Audit log subscriber
- Live event subscriptions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.admin.alerts import AlertEngine, AlertRule, alert_engine
from src.admin.bot import AdminBot, _format_live_event, admin_only
from src.schemas.events import EventType, SystemEvent
from src.security.audit import audit_on_event


# ── Helpers ──────────────────────────────────────────────────────────


def _make_update(*, admin: bool = True, user_id: int = 123456):
    """Build a minimal mock Update."""
    update = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = AsyncMock()
    return update


def _make_context(args: list[str] | None = None):
    """Build a minimal mock context with optional args."""
    ctx = AsyncMock()
    ctx.args = args or []
    return ctx


def _make_event(
    event_type: EventType = EventType.SESSION_STARTED,
    session_id: uuid.UUID | None = None,
    data: dict | None = None,
    **kwargs,
) -> SystemEvent:
    """Create a SystemEvent for testing."""
    return SystemEvent(
        event_type=event_type,
        session_id=session_id or uuid.uuid4(),
        data=data or {},
        **kwargs,
    )


# ── Authorization ───────────────────────────────────────────────────


class TestAdminOnly:
    """Test the admin_only decorator."""

    @pytest.mark.asyncio()
    async def test_authorized_admin_executes(self):
        """Admin user → handler runs."""
        handler = AsyncMock()
        wrapped = admin_only(handler)
        update = _make_update(user_id=123456)
        context = _make_context()

        with patch("src.admin.bot.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [123456]
            await wrapped(update, context)

        handler.assert_awaited_once_with(update, context)

    @pytest.mark.asyncio()
    async def test_unauthorized_user_rejected(self):
        """Non-admin user → '⛔ Non autorizzato.'"""
        handler = AsyncMock()
        wrapped = admin_only(handler)
        update = _make_update(user_id=999999)
        context = _make_context()

        with patch("src.admin.bot.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [123456]
            await wrapped(update, context)

        handler.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with("\u26d4 Non autorizzato.")

    @pytest.mark.asyncio()
    async def test_no_effective_user(self):
        """No effective_user → silently returns."""
        handler = AsyncMock()
        wrapped = admin_only(handler)
        update = AsyncMock()
        update.effective_user = None
        context = _make_context()

        await wrapped(update, context)

        handler.assert_not_awaited()


# ── Command tests ────────────────────────────────────────────────────


class TestCmdHelp:
    """Test /help command."""

    @pytest.mark.asyncio()
    async def test_help_returns_command_list(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        with patch("src.admin.bot.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [123456]
            await bot._cmd_help(update, context)

        reply = update.message.reply_text.call_args
        text = reply.args[0]
        assert "/help" in text
        assert "/health" in text
        assert "/active" in text
        assert "/session" in text
        assert "/today" in text
        assert "/stats" in text
        assert "/errors" in text
        assert "/live" in text
        assert "/unlive" in text


class TestCmdHealth:
    """Test /health command."""

    @pytest.mark.asyncio()
    async def test_health_reports_all_services(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.httpx.AsyncClient") as mock_httpx_cls,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
            patch("src.admin.bot.redis_client") as mock_redis,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_settings.llm.ollama_base_url = "http://localhost:11434"

            # Ollama OK
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # DB OK
            mock_session = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            # Redis OK
            mock_redis.ping = AsyncMock()

            await bot._cmd_health(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Ollama" in text
        assert "PostgreSQL" in text
        assert "Redis" in text


class TestCmdActive:
    """Test /active command."""

    @pytest.mark.asyncio()
    async def test_active_no_sessions(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_active(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Nessuna sessione attiva" in text

    @pytest.mark.asyncio()
    async def test_active_with_sessions(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        # Mock sessions
        sid = uuid.uuid4()
        mock_sess = MagicMock()
        mock_sess.id = sid
        mock_sess.current_state = "employment_type"
        mock_sess.started_at = datetime.now(timezone.utc)
        mock_sess.employment_type = "dipendente"
        mock_user = MagicMock()
        mock_user.first_name = "Mario"
        mock_sess.user = mock_user

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_sess]
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_active(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Sessioni attive" in text
        assert "employment_type" in text
        assert "Mario" in text


class TestCmdSession:
    """Test /session command."""

    @pytest.mark.asyncio()
    async def test_session_no_args(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context(args=[])

        with patch("src.admin.bot.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [123456]
            await bot._cmd_session(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Uso:" in text

    @pytest.mark.asyncio()
    async def test_session_found(self):
        bot = AdminBot()
        update = _make_update()
        sid = uuid.uuid4()
        context = _make_context(args=[str(sid)])

        mock_sess = MagicMock()
        mock_sess.id = sid
        mock_sess.current_state = "result"
        mock_sess.outcome = "qualified"
        mock_sess.started_at = datetime.now(timezone.utc)
        mock_sess.message_count = 12
        mock_sess.employment_type = "dipendente"
        mock_sess.employer_category = "statale"
        mock_sess.pension_source = None
        mock_sess.track_type = "ocr"
        mock_sess.liabilities = []
        mock_sess.dti_calculations = []
        mock_sess.cdq_calculations = []
        mock_sess.product_matches = []

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = mock_sess
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_session(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Sessione" in text
        assert "qualified" in text
        assert "dipendente" in text

    @pytest.mark.asyncio()
    async def test_session_not_found(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context(args=["deadbeef"])

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = None
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_session(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "non trovata" in text


class TestCmdToday:
    """Test /today command."""

    @pytest.mark.asyncio()
    async def test_today_returns_stats(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()

            # Return values for each successive execute call
            count_result = MagicMock()
            count_result.scalar.return_value = 5
            state_result = MagicMock()
            state_result.all.return_value = [("employment_type", 2), ("consent", 1)]

            mock_session.execute.side_effect = [
                count_result,  # total
                count_result,  # completed
                count_result,  # qualified
                count_result,  # abandoned
                count_result,  # errors
                state_result,  # state_counts
            ]
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_today(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Riepilogo di oggi" in text
        assert "Sessioni avviate" in text


class TestCmdErrors:
    """Test /errors command."""

    @pytest.mark.asyncio()
    async def test_errors_none(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_errors(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Nessun errore" in text

    @pytest.mark.asyncio()
    async def test_errors_with_entries(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        err = MagicMock()
        err.created_at = datetime.now(timezone.utc)
        err.event_type = "llm.error"
        err.session_id = uuid.uuid4()
        err.data = {"error": "timeout after 30000ms"}

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [err]
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_errors(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "Errori recenti" in text
        assert "timeout" in text


# ── Live event tests ─────────────────────────────────────────────────


class TestLiveEvents:
    """Test /live, /unlive and on_event."""

    @pytest.mark.asyncio()
    async def test_live_subscribes(self):
        bot = AdminBot()
        update = _make_update()
        sid = uuid.uuid4()
        context = _make_context(args=[str(sid)])

        with (
            patch("src.admin.bot.settings") as mock_settings,
            patch("src.admin.bot.async_session_factory") as mock_db_factory,
        ):
            mock_settings.telegram.admin_ids = [123456]
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.first.return_value = (sid,)
            mock_session.execute.return_value = mock_result
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await bot._cmd_live(update, context)

        assert sid in bot._live_subs
        assert 123456 in bot._live_subs[sid]

    @pytest.mark.asyncio()
    async def test_unlive_unsubscribes(self):
        bot = AdminBot()
        sid = uuid.uuid4()
        bot._live_subs[sid].add(123456)

        update = _make_update()
        context = _make_context(args=[str(sid)[:8]])

        with patch("src.admin.bot.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [123456]
            await bot._cmd_unlive(update, context)

        assert sid not in bot._live_subs

    @pytest.mark.asyncio()
    async def test_on_event_pushes_to_subscribed_admin(self):
        bot = AdminBot()
        bot._app = MagicMock()
        bot._app.bot = AsyncMock()
        sid = uuid.uuid4()
        bot._live_subs[sid].add(123456)

        event = _make_event(
            event_type=EventType.SESSION_STATE_CHANGED,
            session_id=sid,
            data={"from_state": "welcome", "to_state": "consent"},
        )

        await bot.on_event(event)

        bot._app.bot.send_message.assert_awaited_once()
        call_kwargs = bot._app.bot.send_message.call_args.kwargs
        assert "welcome" in call_kwargs["text"]
        assert "consent" in call_kwargs["text"]

    @pytest.mark.asyncio()
    async def test_on_event_no_subscription_no_push(self):
        bot = AdminBot()
        bot._app = MagicMock()
        bot._app.bot = AsyncMock()

        event = _make_event(
            event_type=EventType.MESSAGE_RECEIVED,
            data={"text_length": 42},
        )

        await bot.on_event(event)

        bot._app.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_session_completed_cleans_up_subscriptions(self):
        bot = AdminBot()
        sid = uuid.uuid4()
        bot._live_subs[sid].add(123456)

        event = _make_event(
            event_type=EventType.SESSION_COMPLETED,
            session_id=sid,
            data={"outcome": "qualified"},
        )

        await bot.on_event(event)

        assert sid not in bot._live_subs

    @pytest.mark.asyncio()
    async def test_session_abandoned_cleans_up_subscriptions(self):
        bot = AdminBot()
        sid = uuid.uuid4()
        bot._live_subs[sid].add(123456)

        event = _make_event(
            event_type=EventType.SESSION_ABANDONED,
            session_id=sid,
        )

        await bot.on_event(event)

        assert sid not in bot._live_subs


# ── Live event formatting ────────────────────────────────────────────


class TestFormatLiveEvent:
    """Test _format_live_event."""

    def test_state_changed(self):
        event = _make_event(
            event_type=EventType.SESSION_STATE_CHANGED,
            data={"from_state": "welcome", "to_state": "consent"},
        )
        text = _format_live_event(event)
        assert "welcome" in text
        assert "consent" in text

    def test_message_received(self):
        event = _make_event(
            event_type=EventType.MESSAGE_RECEIVED,
            data={"text_length": 42},
        )
        text = _format_live_event(event)
        assert "42" in text
        assert "Messaggio ricevuto" in text

    def test_unknown_event_type(self):
        event = _make_event(event_type=EventType.CONSENT_GRANTED)
        text = _format_live_event(event)
        assert "consent.granted" in text


# ── Alert engine ─────────────────────────────────────────────────────


class TestAlertEngine:
    """Test alert rule evaluation and message delivery."""

    @pytest.mark.asyncio()
    async def test_eligible_lead_triggers_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.ELIGIBILITY_CHECKED,
            data={"eligible_count": 3},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_awaited_once()
        text = send_fn.call_args.args[1]
        assert "lead qualificato" in text

    @pytest.mark.asyncio()
    async def test_eligible_zero_no_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.ELIGIBILITY_CHECKED,
            data={"eligible_count": 0},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_low_ocr_confidence_triggers_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.OCR_COMPLETED,
            data={"overall_confidence": 0.55, "doc_type": "busta_paga"},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_awaited_once()
        text = send_fn.call_args.args[1]
        assert "bassa confidenza" in text

    @pytest.mark.asyncio()
    async def test_normal_ocr_confidence_no_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.OCR_COMPLETED,
            data={"overall_confidence": 0.95, "doc_type": "busta_paga"},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_llm_timeout_triggers_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.LLM_ERROR,
            data={"error": "timeout", "model": "qwen3:8b", "latency_ms": 30000},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_awaited_once()
        text = send_fn.call_args.args[1]
        assert "LLM timeout" in text

    @pytest.mark.asyncio()
    async def test_llm_non_timeout_error_no_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.LLM_ERROR,
            data={"error": "connection refused", "model": "qwen3:8b"},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_ocr_failed_always_triggers(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.OCR_FAILED,
            data={"error": "VLM parse error"},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_awaited_once()
        text = send_fn.call_args.args[1]
        assert "OCR fallito" in text

    @pytest.mark.asyncio()
    async def test_no_send_fn_does_nothing(self):
        engine = AlertEngine()
        # No set_send_fn call

        event = _make_event(
            event_type=EventType.OCR_FAILED,
            data={"error": "VLM parse error"},
        )

        # Should not raise
        await engine.on_event(event)

    @pytest.mark.asyncio()
    async def test_unrelated_event_type_no_alert(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.CONSENT_GRANTED,
            data={},
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111]
            await engine.on_event(event)

        send_fn.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_sends_to_all_admins(self):
        engine = AlertEngine()
        send_fn = AsyncMock()
        engine.set_send_fn(send_fn)

        event = _make_event(
            event_type=EventType.SYSTEM_ERROR,
            data={"error": "disk full", "source_module": "db"},
            source_module="db",
        )

        with patch("src.admin.alerts.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [111, 222, 333]
            await engine.on_event(event)

        assert send_fn.await_count == 3

    def test_watched_types_covers_rules(self):
        engine = AlertEngine()
        types = engine.watched_types
        assert EventType.ELIGIBILITY_CHECKED in types
        assert EventType.OCR_COMPLETED in types
        assert EventType.OCR_FAILED in types
        assert EventType.LLM_ERROR in types
        assert EventType.SESSION_ESCALATED in types
        assert EventType.SYSTEM_ERROR in types
        assert EventType.DELETION_REQUESTED in types


# ── Audit subscriber ────────────────────────────────────────────────


class TestAuditSubscriber:
    """Test the audit log event subscriber."""

    @pytest.mark.asyncio()
    async def test_event_written_to_db(self):
        event = _make_event(
            event_type=EventType.SESSION_STARTED,
            data={"channel": "telegram"},
            actor_id="user_123",
            actor_role="user",
        )

        with patch("src.security.audit.async_session_factory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await audit_on_event(event)

        mock_session.add.assert_called_once()
        added = mock_session.add.call_args.args[0]
        assert added.event_type == "session.started"
        assert added.actor_id == "user_123"
        assert added.data == {"channel": "telegram"}
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_db_failure_logged_not_raised(self):
        event = _make_event(event_type=EventType.SYSTEM_ERROR)

        with patch("src.security.audit.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("DB connection lost")
            )
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            await audit_on_event(event)


# ── Stub commands ────────────────────────────────────────────────────


class TestStubCommands:
    """Test that stub commands reply with 'in arrivo' message."""

    @pytest.mark.asyncio()
    async def test_stub_command(self):
        bot = AdminBot()
        update = _make_update()
        context = _make_context()

        with patch("src.admin.bot.settings") as mock_settings:
            mock_settings.telegram.admin_ids = [123456]
            await bot._cmd_stub(update, context)

        text = update.message.reply_text.call_args.args[0]
        assert "In arrivo nella prossima versione" in text
