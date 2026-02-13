"""Telegram admin bot — real-time monitoring and management for Giuseppe Giordano.

Separate bot instance from the user bot. Only authorized admins (from
ADMIN_TELEGRAM_IDS env) can use commands. Provides:
- Active session monitoring (/active, /session, /live)
- Daily/weekly summaries (/today, /week)
- System health (/health, /errors)
- Lead management (/dossier, /search, /queue)
- Quick KPIs (/stats)
- Configuration (/config)
- Intervention (/intervene)
- GDPR status (/gdpr)

Runs alongside the user bot in the same FastAPI process.
"""

from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.admin.events import subscribe
from src.config import settings
from src.db.engine import async_session_factory
from src.models.enums import ConversationState, SessionOutcome
from src.models.session import Session
from src.models.user import User
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)

# ── Authorization ───────────────────────────────────────────────────


def _is_admin(user_id: int) -> bool:
    """Check if the Telegram user ID is in the admin list."""
    return user_id in settings.telegram.admin_ids


async def _check_admin(update: Update) -> bool:
    """Verify admin access. Sends rejection message if not authorized."""
    if update.effective_user is None or update.message is None:
        return False
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Non autorizzato.")
        logger.warning(
            "Unauthorized admin access attempt from user_id=%s",
            update.effective_user.id,
        )
        return False
    return True


# ── Live session subscriptions ──────────────────────────────────────

# Maps session_id (str) → set of admin chat_ids subscribed for live updates
_live_subscriptions: dict[str, set[int]] = {}
# Reference to the admin bot Application for sending push messages
_admin_app: Application | None = None


async def _live_event_handler(event: SystemEvent) -> None:
    """Push live event updates to subscribed admins."""
    if _admin_app is None:
        return
    if event.session_id is None:
        return

    session_key = str(event.session_id)
    chat_ids = _live_subscriptions.get(session_key, set())
    if not chat_ids:
        return

    # Format the event for human readability
    text = (
        f"[LIVE #{session_key[:8]}] {event.event_type.value}\n"
        f"{_format_event_data(event.data)}"
    )

    for chat_id in chat_ids:
        try:
            await _admin_app.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Failed to send live update to chat_id=%s", chat_id)


def _format_event_data(data: dict) -> str:
    """Format event data dict into readable lines."""
    if not data:
        return ""
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            continue  # Skip nested dicts for brevity
        lines.append(f"  {key}: {value}")
    return "\n".join(lines[:10])  # Cap at 10 lines


# ── Commands ────────────────────────────────────────────────────────


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — list all admin commands."""
    if not await _check_admin(update):
        return
    assert update.message is not None
    await update.message.reply_text(
        "Admin Commands — BrokerBot\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/active — Sessioni attive\n"
        "/session <id> — Dettaglio sessione\n"
        "/live <id> — Iscriviti ad aggiornamenti live\n"
        "/unlive <id> — Annulla iscrizione live\n"
        "/today — Riepilogo di oggi\n"
        "/week — Riepilogo settimanale\n"
        "/queue — Appuntamenti in coda\n"
        "/search <query> — Cerca sessioni\n"
        "/health — Stato del sistema\n"
        "/errors — Errori ultime 24h\n"
        "/stats — KPI rapidi\n"
        "/config — Configurazione attiva\n"
        "/gdpr — Stato GDPR\n"
        "/help — Questo messaggio"
    )


async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/active — list active (non-terminal) sessions."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    terminal_states = {
        ConversationState.COMPLETED.value,
        ConversationState.ABANDONED.value,
        ConversationState.HUMAN_ESCALATION.value,
    }

    async with async_session_factory() as db:
        result = await db.execute(
            select(Session, User)
            .join(User, Session.user_id == User.id)
            .where(Session.current_state.notin_(terminal_states))
            .order_by(Session.created_at.desc())
            .limit(20)
        )
        rows = result.all()

    if not rows:
        await update.message.reply_text("Nessuna sessione attiva.")
        return

    lines = [f"Sessioni attive: {len(rows)}\n━━━━━━━━━━━━━━━━━━"]
    for session, user in rows:
        name = user.first_name or "—"
        emp = session.employment_type or "—"
        duration = ""
        if session.started_at:
            delta = datetime.now(timezone.utc) - session.started_at
            minutes = int(delta.total_seconds() / 60)
            duration = f"{minutes}min"
        lines.append(
            f"#{str(session.id)[:8]} {name} | {session.current_state} | {emp} | {duration}"
        )

    await update.message.reply_text("\n".join(lines))


async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/session <id> — show full session detail."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    if not context.args:
        await update.message.reply_text("Uso: /session <id>")
        return

    session_prefix = context.args[0]

    async with async_session_factory() as db:
        result = await db.execute(
            select(Session, User)
            .join(User, Session.user_id == User.id)
            .where(Session.id.cast(str).startswith(session_prefix))
            .limit(1)
        )
        row = result.first()

    if row is None:
        await update.message.reply_text(f"Sessione {session_prefix} non trovata.")
        return

    session, user = row
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "—"
    emp = session.employment_type or "—"
    emp_cat = session.employer_category or "—"
    track = session.track_type or "—"
    outcome = session.outcome or "in corso"

    duration = ""
    if session.started_at:
        end = session.completed_at or datetime.now(timezone.utc)
        delta = end - session.started_at
        minutes = int(delta.total_seconds() / 60)
        seconds = int(delta.total_seconds() % 60)
        duration = f"{minutes}m {seconds}s"

    text = (
        f"SESSIONE #{str(session.id)[:8]}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Utente:      {name}\n"
        f"Stato:       {session.current_state}\n"
        f"Esito:       {outcome}\n"
        f"Durata:      {duration}\n"
        f"Impiego:     {emp}\n"
        f"Categoria:   {emp_cat}\n"
        f"Track:       {track}\n"
        f"Messaggi:    {session.message_count}\n"
        f"Documenti:   {len(session.documents)}\n"
        f"Passività:   {len(session.liabilities)}\n"
        f"Prodotti:    {len(session.product_matches)}\n"
    )

    await update.message.reply_text(text)


async def live_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/live <id> — subscribe to real-time updates for a session."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    if not context.args:
        await update.message.reply_text("Uso: /live <id>")
        return

    session_id = context.args[0]
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return

    _live_subscriptions.setdefault(session_id, set()).add(chat_id)
    await update.message.reply_text(
        f"Iscritto agli aggiornamenti live per sessione {session_id}."
    )


async def unlive_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unlive <id> — unsubscribe from session updates."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    if not context.args:
        await update.message.reply_text("Uso: /unlive <id>")
        return

    session_id = context.args[0]
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return

    subs = _live_subscriptions.get(session_id, set())
    subs.discard(chat_id)
    await update.message.reply_text(
        f"Rimosso dagli aggiornamenti live per sessione {session_id}."
    )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/today — today's summary."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as db:
        # Total sessions started today
        total = await db.scalar(
            select(func.count(Session.id)).where(Session.created_at >= start_of_day)
        )

        # Completed today
        completed = await db.scalar(
            select(func.count(Session.id)).where(
                Session.completed_at >= start_of_day,
                Session.outcome.isnot(None),
            )
        )

        # By outcome
        qualified = await db.scalar(
            select(func.count(Session.id)).where(
                Session.completed_at >= start_of_day,
                Session.outcome == SessionOutcome.QUALIFIED.value,
            )
        )

        scheduled = await db.scalar(
            select(func.count(Session.id)).where(
                Session.completed_at >= start_of_day,
                Session.outcome == SessionOutcome.SCHEDULED.value,
            )
        )

        escalated = await db.scalar(
            select(func.count(Session.id)).where(
                Session.completed_at >= start_of_day,
                Session.outcome == SessionOutcome.HUMAN_ESCALATION.value,
            )
        )

    text = (
        f"Riepilogo oggi ({now.strftime('%d/%m/%Y')})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Sessioni avviate:  {total or 0}\n"
        f"Completate:        {completed or 0}\n"
        f"Idonei:            {qualified or 0}\n"
        f"Chiamate prenot.:  {scheduled or 0}\n"
        f"Escalation:        {escalated or 0}\n"
    )

    await update.message.reply_text(text)


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/week — weekly summary."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    now = datetime.now(timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as db:
        total = await db.scalar(
            select(func.count(Session.id)).where(Session.created_at >= start_of_week)
        )
        completed = await db.scalar(
            select(func.count(Session.id)).where(
                Session.completed_at >= start_of_week,
                Session.outcome.isnot(None),
            )
        )
        qualified = await db.scalar(
            select(func.count(Session.id)).where(
                Session.completed_at >= start_of_week,
                Session.outcome == SessionOutcome.QUALIFIED.value,
            )
        )

    conv_rate = 0.0
    if total and total > 0:
        conv_rate = ((qualified or 0) / total) * 100

    text = (
        f"Riepilogo settimanale\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Sessioni:    {total or 0}\n"
        f"Completate:  {completed or 0}\n"
        f"Idonei:      {qualified or 0}\n"
        f"Tasso conv:  {conv_rate:.1f}%\n"
    )

    await update.message.reply_text(text)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/health — system health status."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    checks: list[str] = []

    # Python version
    checks.append(f"Python: {sys.version.split()[0]}")
    checks.append(f"Platform: {platform.system()} {platform.release()}")

    # Database check
    try:
        async with async_session_factory() as db:
            await db.execute(select(func.count(Session.id)))
        checks.append("PostgreSQL: OK")
    except Exception as e:
        checks.append(f"PostgreSQL: ERRORE — {e}")

    # LLM check
    try:
        from src.llm.client import llm_client
        status = "caricato" if llm_client._current_model else "non caricato"
        checks.append(f"Ollama: {status} ({settings.llm.ollama_base_url})")
    except Exception as e:
        checks.append(f"Ollama: ERRORE — {e}")

    # Redis check
    try:
        from src.db.engine import redis_client
        if redis_client is not None:
            await redis_client.ping()
            checks.append("Redis: OK")
        else:
            checks.append("Redis: non connesso")
    except Exception as e:
        checks.append(f"Redis: ERRORE — {e}")

    # Environment
    checks.append(f"Ambiente: {settings.environment}")
    checks.append(f"Log level: {settings.log_level}")

    text = "Stato Sistema\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(checks)
    await update.message.reply_text(text)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — quick KPIs."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    async with async_session_factory() as db:
        total_sessions = await db.scalar(select(func.count(Session.id)))
        total_users = await db.scalar(select(func.count(User.id)))
        completed = await db.scalar(
            select(func.count(Session.id)).where(Session.outcome.isnot(None))
        )
        qualified = await db.scalar(
            select(func.count(Session.id)).where(
                Session.outcome == SessionOutcome.QUALIFIED.value
            )
        )

    qual_rate = 0.0
    if completed and completed > 0:
        qual_rate = ((qualified or 0) / completed) * 100

    text = (
        f"KPI Rapidi\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Utenti totali:     {total_users or 0}\n"
        f"Sessioni totali:   {total_sessions or 0}\n"
        f"Completate:        {completed or 0}\n"
        f"Idonei:            {qualified or 0}\n"
        f"Tasso qualifica:   {qual_rate:.1f}%\n"
    )

    await update.message.reply_text(text)


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/config — show current configuration."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    text = (
        f"Configurazione\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ambiente:      {settings.environment}\n"
        f"Bot name:      {settings.branding.bot_name}\n"
        f"Legal entity:  {settings.branding.legal_entity}\n"
        f"OAM:           {settings.branding.oam_number}\n"
        f"LLM conv:      {settings.llm.conversation_model}\n"
        f"LLM vision:    {settings.llm.vision_model}\n"
        f"LLM timeout:   {settings.llm.conversation_timeout}s\n"
        f"OCR timeout:   {settings.llm.ocr_timeout}s\n"
        f"Data retention: {settings.data_retention_months} mesi\n"
        f"Doc retention:  {settings.document_retention_days} giorni\n"
    )

    await update.message.reply_text(text)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/search <query> — search sessions by user name or telegram_id."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    if not context.args:
        await update.message.reply_text("Uso: /search <nome o id>")
        return

    query = " ".join(context.args).strip()

    async with async_session_factory() as db:
        # Search by first_name, last_name, or telegram_id
        result = await db.execute(
            select(Session, User)
            .join(User, Session.user_id == User.id)
            .where(
                User.first_name.ilike(f"%{query}%")
                | User.last_name.ilike(f"%{query}%")
                | User.telegram_id.ilike(f"%{query}%")
            )
            .order_by(Session.created_at.desc())
            .limit(10)
        )
        rows = result.all()

    if not rows:
        await update.message.reply_text(f"Nessun risultato per '{query}'.")
        return

    lines = [f"Risultati per '{query}': {len(rows)}\n━━━━━━━━━━━━━━━━━━"]
    for session, user in rows:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "—"
        lines.append(
            f"#{str(session.id)[:8]} {name} | {session.current_state} | {session.outcome or 'in corso'}"
        )

    await update.message.reply_text("\n".join(lines))


async def gdpr_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/gdpr — GDPR status overview."""
    if not await _check_admin(update):
        return
    assert update.message is not None

    async with async_session_factory() as db:
        total_users = await db.scalar(select(func.count(User.id)))
        anonymized = await db.scalar(
            select(func.count(User.id)).where(User.anonymized.is_(True))
        )

    text = (
        f"Stato GDPR\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Utenti totali:     {total_users or 0}\n"
        f"Anonimizzati:      {anonymized or 0}\n"
        f"Retention dati:    {settings.data_retention_months} mesi\n"
        f"Retention documenti: {settings.document_retention_days} giorni\n"
    )

    await update.message.reply_text(text)


# ── Bot factory ─────────────────────────────────────────────────────


def create_admin_bot() -> Application:
    """Build and configure the Telegram admin bot application.

    Returns the Application instance (not yet started).
    Registers all admin commands and subscribes to the event system
    for live session updates.
    """
    global _admin_app

    token = settings.telegram.telegram_admin_bot_token
    if not token:
        msg = "TELEGRAM_ADMIN_BOT_TOKEN not set in environment"
        raise ValueError(msg)

    app = Application.builder().token(token).build()
    _admin_app = app

    # Register command handlers
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("active", active_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("live", live_command))
    app.add_handler(CommandHandler("unlive", unlive_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("config", config_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("gdpr", gdpr_command))

    # Subscribe to event system for live updates
    subscribe(
        _live_event_handler,
        event_types=[
            EventType.SESSION_STATE_CHANGED,
            EventType.MESSAGE_RECEIVED,
            EventType.MESSAGE_SENT,
            EventType.OCR_COMPLETED,
            EventType.OCR_FAILED,
            EventType.DATA_EXTRACTED,
            EventType.DTI_CALCULATED,
            EventType.CDQ_CALCULATED,
            EventType.ELIGIBILITY_CHECKED,
            EventType.APPOINTMENT_BOOKED,
            EventType.SESSION_ESCALATED,
            EventType.SYSTEM_ERROR,
        ],
    )

    logger.info("Admin bot application created with %d commands", 12)
    return app
