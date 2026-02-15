"""Telegram admin bot — monitoring, live session tracking, and system health.

Provides 9 core commands for real-time system visibility:
/help, /health, /active, /session, /today, /stats, /errors, /live, /unlive

Uses python-telegram-bot v21+ async. All commands are restricted to admins
listed in ADMIN_TELEGRAM_IDS.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

import httpx
from sqlalchemy import String, func, select, text
from sqlalchemy.sql.expression import cast
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from src.admin.events import subscribe, unsubscribe
from src.config import settings
from src.db.engine import async_session_factory, redis_client
from src.models.audit import AuditLog
from src.models.session import Session
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


# ── Authorization ────────────────────────────────────────────────────


def admin_only(
    func_: Callable[..., Coroutine[Any, Any, None]],
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Decorator — rejects non-admin users with a denial message.

    Works on both standalone functions (update, context) and
    bound methods (self, update, context).
    """

    @wraps(func_)
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        # update is always second-to-last arg: (update, context) or (self, update, context)
        update: Update = args[-2]
        if update.effective_user is None:
            return
        if update.effective_user.id not in settings.telegram.admin_ids:
            if update.message:
                await update.message.reply_text("\u26d4 Non autorizzato.")
            return
        await func_(*args, **kwargs)

    return wrapper


# ── Live event formatting ────────────────────────────────────────────

_EVENT_FORMATS: dict[EventType, str] = {
    EventType.SESSION_STATE_CHANGED: "\U0001f504 Stato: {from_state} \u2192 {to_state}",
    EventType.MESSAGE_RECEIVED: "\U0001f4ac Messaggio ricevuto ({text_length} char)",
    EventType.MESSAGE_SENT: "\U0001f4e4 Risposta inviata ({text_length} char)",
    EventType.DOCUMENT_RECEIVED: "\U0001f4ce Documento ricevuto",
    EventType.OCR_STARTED: "\U0001f50d OCR avviato: {doc_type}",
    EventType.OCR_COMPLETED: "\U0001f4c4 OCR completato: {doc_type} (conf: {overall_confidence:.0%})",
    EventType.OCR_FAILED: "\u274c OCR fallito: {error}",
    EventType.DATA_EXTRACTED: "\U0001f4cb Dati estratti: {field_count} campi",
    EventType.ELIGIBILITY_CHECKED: "\u2705 Eligibilit\u00e0: {eligible_count} prodotti",
    EventType.SESSION_COMPLETED: "\U0001f3c1 Sessione completata: {outcome}",
    EventType.SESSION_ABANDONED: "\U0001f6ab Sessione abbandonata",
    EventType.SESSION_ESCALATED: "\U0001f6a8 Escalation umana",
    EventType.LLM_RESPONSE: "\U0001f916 LLM risposta ({latency_ms}ms)",
}


def _format_live_event(event: SystemEvent) -> str:
    """Format a SystemEvent for /live push notification."""
    template = _EVENT_FORMATS.get(event.event_type)
    if template is None:
        return f"\U0001f514 {event.event_type.value}"

    ctx: dict[str, Any] = {**event.data}
    # Provide fallbacks for common keys
    ctx.setdefault("from_state", "?")
    ctx.setdefault("to_state", "?")
    ctx.setdefault("text_length", "?")
    ctx.setdefault("doc_type", "?")
    ctx.setdefault("overall_confidence", 0.0)
    ctx.setdefault("error", "sconosciuto")
    ctx.setdefault("field_count", "?")
    ctx.setdefault("eligible_count", 0)
    ctx.setdefault("outcome", "?")
    ctx.setdefault("latency_ms", "?")

    try:
        return template.format(**ctx)
    except (KeyError, ValueError):
        return f"\U0001f514 {event.event_type.value}: {ctx}"


# ── AdminBot ─────────────────────────────────────────────────────────


class AdminBot:
    """Telegram admin bot for monitoring and system visibility."""

    def __init__(self) -> None:
        self._app: Application | None = None
        self._live_subs: dict[uuid.UUID, set[int]] = defaultdict(set)

    async def start(self) -> None:
        """Build Application, register handlers, start polling, subscribe to events."""
        token = settings.telegram.telegram_admin_bot_token
        if not token:
            logger.warning("TELEGRAM_ADMIN_BOT_TOKEN not set — admin bot disabled")
            return

        self._app = Application.builder().token(token).build()

        # Core commands
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("health", self._cmd_health))
        self._app.add_handler(CommandHandler("active", self._cmd_active))
        self._app.add_handler(CommandHandler("session", self._cmd_session))
        self._app.add_handler(CommandHandler("today", self._cmd_today))
        self._app.add_handler(CommandHandler("stats", self._cmd_stats))
        self._app.add_handler(CommandHandler("errors", self._cmd_errors))
        self._app.add_handler(CommandHandler("live", self._cmd_live))
        self._app.add_handler(CommandHandler("unlive", self._cmd_unlive))

        # Stub commands (Phase 2)
        for stub in ("search", "queue", "dossier", "week", "alerts", "intervene", "config", "gdpr"):
            self._app.add_handler(CommandHandler(stub, self._cmd_stub))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]

        # Subscribe to live events
        subscribe(self.on_event)

        logger.info("Admin bot started")

    async def stop(self) -> None:
        """Stop polling, unsubscribe, shutdown."""
        unsubscribe(self.on_event)

        if self._app is not None:
            if self._app.updater:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

        logger.info("Admin bot stopped")

    async def on_event(self, event: SystemEvent) -> None:
        """Push live session events to subscribed admins."""
        if event.session_id is None:
            return

        # Auto-cleanup on session end
        if event.event_type in (EventType.SESSION_COMPLETED, EventType.SESSION_ABANDONED):
            self._live_subs.pop(event.session_id, None)
            return

        admin_ids = self._live_subs.get(event.session_id)
        if not admin_ids:
            return

        session_short = str(event.session_id)[:8]
        text = f"\U0001f4e1 <b>[{session_short}]</b> {_format_live_event(event)}"

        for admin_id in admin_ids:
            try:
                await self.send_to_admin(admin_id, text)
            except Exception:
                logger.exception("Failed to push live event to admin %d", admin_id)

    async def send_to_admins(self, text: str) -> None:
        """Send a message to all admin IDs."""
        for admin_id in settings.telegram.admin_ids:
            await self.send_to_admin(admin_id, text)

    async def send_to_admin(self, admin_id: int, text: str) -> None:
        """Send a message to a specific admin."""
        if self._app is None:
            return
        try:
            await self._app.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.exception("Failed to send message to admin %d", admin_id)

    # ── Command handlers ─────────────────────────────────────────────

    @admin_only
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/help — list all commands."""
        text = (
            "\U0001f916 <b>BrokerBot Admin</b>\n\n"
            "<b>Comandi disponibili:</b>\n"
            "/help \u2014 Mostra questo messaggio\n"
            "/health \u2014 Stato servizi (Ollama, DB, Redis)\n"
            "/active \u2014 Sessioni attive\n"
            "/session &lt;id&gt; \u2014 Dettaglio sessione\n"
            "/today \u2014 Riepilogo giornaliero\n"
            "/stats \u2014 KPI principali\n"
            "/errors \u2014 Errori recenti (24h)\n"
            "/live &lt;id&gt; \u2014 Segui sessione in tempo reale\n"
            "/unlive &lt;id&gt; \u2014 Smetti di seguire\n\n"
            "<b>In arrivo:</b>\n"
            "/search, /queue, /dossier, /week, /alerts, /intervene, /config, /gdpr"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)  # type: ignore[union-attr]

    @admin_only
    async def _cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/health — check Ollama, DB, Redis connectivity."""
        parts: list[str] = ["\U0001f3e5 <b>Stato servizi</b>\n"]

        # Ollama
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.llm.ollama_base_url}/api/tags")
                resp.raise_for_status()
            ms = int((time.monotonic() - t0) * 1000)
            parts.append(f"\u2705 Ollama: OK ({ms}ms)")
        except Exception as exc:
            parts.append(f"\u274c Ollama: {exc}")

        # Database
        try:
            t0 = time.monotonic()
            async with async_session_factory() as db:
                await db.execute(text("SELECT 1"))
            ms = int((time.monotonic() - t0) * 1000)
            parts.append(f"\u2705 PostgreSQL: OK ({ms}ms)")
        except Exception as exc:
            parts.append(f"\u274c PostgreSQL: {exc}")

        # Redis
        try:
            t0 = time.monotonic()
            await redis_client.ping()
            ms = int((time.monotonic() - t0) * 1000)
            parts.append(f"\u2705 Redis: OK ({ms}ms)")
        except Exception as exc:
            parts.append(f"\u274c Redis: {exc}")

        await update.message.reply_text(  # type: ignore[union-attr]
            "\n".join(parts), parse_mode=ParseMode.HTML
        )

    @admin_only
    async def _cmd_active(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/active — list sessions where outcome IS NULL."""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(Session)
                    .where(Session.outcome.is_(None))
                    .order_by(Session.started_at.desc())
                    .limit(20)
                )
                sessions = result.scalars().all()
        except Exception:
            logger.exception("Failed to query active sessions")
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u274c Errore nel recupero delle sessioni."
            )
            return

        if not sessions:
            await update.message.reply_text(  # type: ignore[union-attr]
                "\U0001f4ad Nessuna sessione attiva."
            )
            return

        lines: list[str] = [f"\U0001f4cb <b>Sessioni attive ({len(sessions)})</b>\n"]
        now = datetime.now(UTC)
        for s in sessions:
            short_id = str(s.id)[:8]
            duration = now - s.started_at
            mins = int(duration.total_seconds() // 60)
            emp = s.employment_type or "-"
            name = s.user.first_name if s.user else "-"
            lines.append(
                f"<code>{short_id}</code> | {s.current_state} | {mins}min | {emp} | {name}\n"
                f"  \u2192 /session {short_id}"
            )

        await update.message.reply_text(  # type: ignore[union-attr]
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    @admin_only
    async def _cmd_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/session <id> — full session detail."""
        if not context.args:
            await update.message.reply_text(  # type: ignore[union-attr]
                "Uso: /session &lt;id&gt; (primi 8 caratteri o UUID completo)",
                parse_mode=ParseMode.HTML,
            )
            return

        session_id_str = context.args[0]

        try:
            async with async_session_factory() as db:
                if len(session_id_str) < 36:
                    result = await db.execute(
                        select(Session).where(
                            cast(Session.id, String).like(f"{session_id_str}%")
                        )
                    )
                else:
                    result = await db.execute(
                        select(Session).where(Session.id == uuid.UUID(session_id_str))
                    )
                session = result.scalars().first()
        except Exception:
            logger.exception("Failed to query session %s", session_id_str)
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u274c Errore nel recupero della sessione."
            )
            return

        if session is None:
            await update.message.reply_text(  # type: ignore[union-attr]
                f"\u274c Sessione <code>{session_id_str}</code> non trovata.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Build detail sections
        short_id = str(session.id)[:8]
        now = datetime.now(UTC)
        duration = now - session.started_at
        mins = int(duration.total_seconds() // 60)

        lines: list[str] = [
            f"\U0001f4c1 <b>Sessione {short_id}</b>\n",
            f"<b>Stato:</b> {session.current_state}",
            f"<b>Esito:</b> {session.outcome or 'in corso'}",
            f"<b>Durata:</b> {mins} min",
            f"<b>Messaggi:</b> {session.message_count}",
        ]

        # Collected data
        if session.employment_type:
            lines.append(f"\n<b>Tipo impiego:</b> {session.employment_type}")
        if session.employer_category:
            lines.append(f"<b>Datore:</b> {session.employer_category}")
        if session.pension_source:
            lines.append(f"<b>Pensione:</b> {session.pension_source}")
        if session.track_type:
            lines.append(f"<b>Percorso:</b> {session.track_type}")

        # Liabilities
        if session.liabilities:
            lines.append(f"\n<b>Debiti:</b> {len(session.liabilities)}")

        # Calculations
        if session.dti_calculations:
            latest_dti = session.dti_calculations[-1]
            data = latest_dti.input_data or {}
            lines.append(f"\n<b>DTI:</b> {data.get('dti_ratio', '?')}")
        if session.cdq_calculations:
            lines.append(f"<b>CdQ calcoli:</b> {len(session.cdq_calculations)}")

        # Product matches
        if session.product_matches:
            eligible = [pm for pm in session.product_matches if pm.eligible]
            lines.append(f"\n<b>Prodotti idonei:</b> {len(eligible)}/{len(session.product_matches)}")
            for pm in eligible:
                lines.append(f"  \u2022 {pm.product_name}")

        lines.append(f"\n/live {short_id}")

        await update.message.reply_text(  # type: ignore[union-attr]
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    @admin_only
    async def _cmd_today(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/today — today's summary."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        try:
            async with async_session_factory() as db:
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

                # Active sessions states
                result = await db.execute(
                    select(Session.current_state, func.count(Session.id))
                    .where(Session.outcome.is_(None))
                    .group_by(Session.current_state)
                )
                state_counts = result.all()
        except Exception:
            logger.exception("Failed to query today stats")
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u274c Errore nel recupero delle statistiche."
            )
            return

        qual_rate = f"{qualified / completed:.0%}" if completed > 0 else "N/A"

        lines = [
            "\U0001f4c5 <b>Riepilogo di oggi</b>\n",
            f"<b>Sessioni avviate:</b> {total}",
            f"<b>Completate:</b> {completed}",
            f"<b>Abbandonate:</b> {abandoned}",
            f"<b>Tasso qualificazione:</b> {qual_rate}",
            f"<b>Errori:</b> {errors}",
        ]

        if state_counts:
            lines.append("\n<b>Sessioni attive per stato:</b>")
            for state, count in state_counts:
                lines.append(f"  {state}: {count}")

        await update.message.reply_text(  # type: ignore[union-attr]
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    @admin_only
    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/stats — quick KPIs."""
        week_ago = datetime.now(UTC) - timedelta(days=7)

        try:
            async with async_session_factory() as db:
                # Total sessions all time
                result = await db.execute(select(func.count(Session.id)))
                total = result.scalar() or 0

                # Completed last 7 days
                result = await db.execute(
                    select(func.count(Session.id)).where(
                        Session.started_at >= week_ago,
                        Session.outcome.isnot(None),
                    )
                )
                completed_7d = result.scalar() or 0

                # Qualified last 7 days
                result = await db.execute(
                    select(func.count(Session.id)).where(
                        Session.started_at >= week_ago,
                        Session.outcome == "qualified",
                    )
                )
                qualified_7d = result.scalar() or 0

                # Average messages per session
                result = await db.execute(
                    select(func.avg(Session.message_count)).where(Session.outcome.isnot(None))
                )
                avg_msgs = result.scalar()
                avg_msgs_str = f"{avg_msgs:.1f}" if avg_msgs else "N/A"

                # Top employment types
                result = await db.execute(
                    select(Session.employment_type, func.count(Session.id))
                    .where(Session.employment_type.isnot(None))
                    .group_by(Session.employment_type)
                    .order_by(func.count(Session.id).desc())
                    .limit(5)
                )
                emp_types = result.all()
        except Exception:
            logger.exception("Failed to query stats")
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u274c Errore nel recupero delle statistiche."
            )
            return

        qual_rate = f"{qualified_7d / completed_7d:.0%}" if completed_7d > 0 else "N/A"

        lines = [
            "\U0001f4ca <b>KPI</b>\n",
            f"<b>Sessioni totali:</b> {total}",
            f"<b>Qualificazione (7gg):</b> {qual_rate} ({qualified_7d}/{completed_7d})",
            f"<b>Media messaggi/sessione:</b> {avg_msgs_str}",
        ]

        if emp_types:
            lines.append("\n<b>Tipi impiego:</b>")
            for emp, count in emp_types:
                lines.append(f"  {emp}: {count}")

        await update.message.reply_text(  # type: ignore[union-attr]
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    @admin_only
    async def _cmd_errors(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/errors — recent errors (24h)."""
        since = datetime.now(UTC) - timedelta(hours=24)

        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.created_at >= since,
                        AuditLog.event_type.like("%error%") | AuditLog.event_type.like("%failed%"),
                    )
                    .order_by(AuditLog.created_at.desc())
                    .limit(20)
                )
                errors = result.scalars().all()
        except Exception:
            logger.exception("Failed to query errors")
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u274c Errore nel recupero degli errori."
            )
            return

        if not errors:
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u2705 Nessun errore nelle ultime 24h."
            )
            return

        lines = [f"\u26a0\ufe0f <b>Errori recenti ({len(errors)})</b>\n"]
        for err in errors:
            ts = err.created_at.strftime("%H:%M:%S") if err.created_at else "?"
            session_short = str(err.session_id)[:8] if err.session_id else "-"
            error_msg = ""
            if err.data and isinstance(err.data, dict):
                error_msg = str(err.data.get("error", ""))[:80]
            lines.append(
                f"<code>{ts}</code> | {err.event_type} | {session_short}\n"
                f"  {error_msg}"
            )

        await update.message.reply_text(  # type: ignore[union-attr]
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    @admin_only
    async def _cmd_live(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/live <id> — subscribe to real-time events for a session."""
        if not context.args:
            await update.message.reply_text(  # type: ignore[union-attr]
                "Uso: /live &lt;session_id&gt;",
                parse_mode=ParseMode.HTML,
            )
            return

        session_id_str = context.args[0]

        # Resolve short UUID
        try:
            async with async_session_factory() as db:
                if len(session_id_str) < 36:
                    result = await db.execute(
                        select(Session.id).where(
                            cast(Session.id, String).like(f"{session_id_str}%")
                        )
                    )
                else:
                    result = await db.execute(
                        select(Session.id).where(Session.id == uuid.UUID(session_id_str))
                    )
                row = result.first()
        except Exception:
            logger.exception("Failed to resolve session for /live")
            await update.message.reply_text(  # type: ignore[union-attr]
                "\u274c Errore nel recupero della sessione."
            )
            return

        if row is None:
            await update.message.reply_text(  # type: ignore[union-attr]
                f"\u274c Sessione <code>{session_id_str}</code> non trovata.",
                parse_mode=ParseMode.HTML,
            )
            return

        session_id = row[0]
        admin_id = update.effective_user.id  # type: ignore[union-attr]
        self._live_subs[session_id].add(admin_id)

        await update.message.reply_text(  # type: ignore[union-attr]
            f"\U0001f4e1 Ora segui la sessione <code>{str(session_id)[:8]}</code> in tempo reale.\n"
            f"Usa /unlive {str(session_id)[:8]} per smettere.",
            parse_mode=ParseMode.HTML,
        )

    @admin_only
    async def _cmd_unlive(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/unlive <id> — unsubscribe from a session."""
        if not context.args:
            await update.message.reply_text(  # type: ignore[union-attr]
                "Uso: /unlive &lt;session_id&gt;",
                parse_mode=ParseMode.HTML,
            )
            return

        session_id_str = context.args[0]
        admin_id = update.effective_user.id  # type: ignore[union-attr]

        # Find matching session in subscriptions
        for sid in list(self._live_subs.keys()):
            if str(sid).startswith(session_id_str):
                self._live_subs[sid].discard(admin_id)
                if not self._live_subs[sid]:
                    del self._live_subs[sid]
                await update.message.reply_text(  # type: ignore[union-attr]
                    f"\U0001f515 Non segui pi\u00f9 la sessione <code>{str(sid)[:8]}</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

        await update.message.reply_text(  # type: ignore[union-attr]
            f"\u274c Nessun abbonamento trovato per <code>{session_id_str}</code>.",
            parse_mode=ParseMode.HTML,
        )

    @admin_only
    async def _cmd_stub(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Stub handler for Phase 2 commands."""
        await update.message.reply_text(  # type: ignore[union-attr]
            "\U0001f6a7 In arrivo nella prossima versione."
        )


# Module-level singleton
admin_bot = AdminBot()
