"""Telegram user bot adapter — handles incoming messages via long-polling or webhook.

Uses python-telegram-bot v21+ async. Routes messages to the conversation engine
and sends responses back to the user.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from telegram import Bot, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import settings
from src.conversation.engine import conversation_engine
from src.db.engine import async_session_factory, redis_client
from src.models.deletion import DataDeletionRequest
from src.models.enums import ConversationState, DeletionRequestStatus, SessionOutcome
from src.models.session import Session
from src.models.user import User
from src.security.consent import consent_manager
from src.security.erasure import erasure_processor

logger = logging.getLogger(__name__)

# ── Webhook router ───────────────────────────────────────────────────

telegram_router = APIRouter(prefix="/webhook", tags=["telegram"])


@telegram_router.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram updates via webhook (production mode)."""
    # Verify secret header if configured
    secret = settings.telegram.telegram_webhook_secret
    if secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != secret:
            return Response(status_code=403)

    telegram_app: Application = request.app.state.telegram_app
    bot: Bot = telegram_app.bot

    data = await request.json()
    update = Update.de_json(data, bot)

    # Fire-and-forget — return 200 immediately so Telegram doesn't retry
    asyncio.create_task(telegram_app.process_update(update))

    return Response(status_code=200)

# Interval between "typing..." indicator refreshes (Telegram typing expires after ~5s)
_TYPING_INTERVAL = 4.0


async def _send_typing_until_done(chat_id: int, bot: object, done_event: asyncio.Event) -> None:
    """Send typing action every few seconds until the done event is set."""
    while not done_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)  # type: ignore[union-attr]
        except Exception:
            break
        try:
            await asyncio.wait_for(done_event.wait(), timeout=_TYPING_INTERVAL)
        except TimeoutError:
            continue


async def _process_with_typing(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    first_name: str | None,
    image_bytes: bytes | None = None,
) -> None:
    """Process a message while showing a typing indicator to the user."""
    assert update.effective_user is not None  # noqa: S101
    assert update.message is not None  # noqa: S101

    telegram_id = str(update.effective_user.id)
    chat_id = update.message.chat_id

    # Start typing indicator in background
    done = asyncio.Event()
    typing_task = asyncio.create_task(_send_typing_until_done(chat_id, context.bot, done))

    try:
        async with async_session_factory() as db:
            response = await conversation_engine.process_message(
                db=db,
                channel_user_id=telegram_id,
                text=text,
                first_name=first_name,
                image_bytes=image_bytes,
                channel="telegram",
            )
            await db.commit()
    except Exception:
        logger.exception("Error processing message from user %s", telegram_id)
        response = (
            "Mi scusi, si \u00e8 verificato un errore. "
            "Riprovi tra qualche istante o chiami il 800.99.00.90."
        )
    finally:
        done.set()
        await typing_task

    await update.message.reply_text(response)


async def _close_active_session(telegram_id: str) -> bool:
    """Mark the user's active session as ABANDONED and clear its Redis cache.

    Returns True if a session was closed, False if none was active.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            select(Session)
            .join(User, Session.user_id == User.id)
            .where(User.telegram_id == telegram_id)
            .where(Session.current_state.notin_([
                ConversationState.COMPLETED.value,
                ConversationState.ABANDONED.value,
                ConversationState.HUMAN_ESCALATION.value,
            ]))
            .order_by(Session.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False

        session.current_state = ConversationState.ABANDONED.value
        session.outcome = SessionOutcome.ABANDONED.value
        await db.commit()

        # Clear Redis message cache
        try:
            await redis_client.delete(f"session:{session.id}:messages")
        except Exception:
            pass

        logger.info("Closed session %s for user %s", session.id, telegram_id)
        return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command — close any active session and begin a new one."""
    if update.effective_user is None or update.message is None:
        return
    telegram_id = str(update.effective_user.id)
    await _close_active_session(telegram_id)
    await _process_with_typing(update, context, "/start", update.effective_user.first_name)


async def nuova_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/nuova command — end current session and start fresh."""
    if update.effective_user is None or update.message is None:
        return
    telegram_id = str(update.effective_user.id)
    closed = await _close_active_session(telegram_id)
    if closed:
        await update.message.reply_text("Sessione precedente chiusa. Iniziamo da capo!")
    await _process_with_typing(update, context, "/start", update.effective_user.first_name)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — route to conversation engine."""
    if update.effective_user is None or update.message is None or update.message.text is None:
        return

    # Check for pending deletion confirmation
    if context.user_data.get("awaiting_deletion_confirm"):  # type: ignore[union-attr]
        context.user_data["awaiting_deletion_confirm"] = False  # type: ignore[index]

        if update.message.text.strip().upper() == "CONFERMO":
            telegram_id = str(update.effective_user.id)
            try:
                async with async_session_factory() as db:
                    user = await _find_user_by_telegram_id(db, telegram_id)
                    if user is None or user.anonymized:
                        await update.message.reply_text("Non risultano dati da eliminare.")
                        return

                    request = await erasure_processor.request_erasure(db, user.id)
                    result = await erasure_processor.process_erasure(db, request.id)
                    await db.commit()

                if result.success:
                    await update.message.reply_text(
                        "Cancellazione completata.\n\n"
                        f"Sessioni: {result.sessions}\n"
                        f"Messaggi redatti: {result.messages}\n"
                        f"Documenti eliminati: {result.documents}\n"
                        f"Dati estratti eliminati: {result.extracted_data}\n\n"
                        "I suoi dati personali sono stati anonimizzati.\n"
                        "Per qualsiasi domanda: privacy@primonetwork.it"
                    )
                else:
                    await update.message.reply_text(
                        "Si e' verificato un errore durante la cancellazione.\n"
                        "La richiesta e' stata registrata e sara' elaborata manualmente.\n"
                        "Per assistenza: privacy@primonetwork.it"
                    )
            except Exception:
                logger.exception("Error processing erasure for user %s", telegram_id)
                await update.message.reply_text(
                    "Si e' verificato un errore. La richiesta e' stata registrata.\n"
                    "Per assistenza: privacy@primonetwork.it"
                )
        else:
            await update.message.reply_text(
                "Richiesta di cancellazione annullata.\n"
                "Puo' riprendere la conversazione normalmente."
            )
        return

    await _process_with_typing(update, context, update.message.text, update.effective_user.first_name)


async def handle_photo_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos and image documents — download and route to conversation engine."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = str(update.effective_user.id)
    text = update.message.caption or "[documento inviato]"

    try:
        if update.message.photo:
            # Grab the highest-resolution variant (last in list)
            file = await update.message.photo[-1].get_file()
        elif update.message.document:
            file = await update.message.document.get_file()
        else:
            return

        data = await file.download_as_bytearray()
        image_bytes = bytes(data)
    except Exception:
        logger.exception("Failed to download file from user %s", telegram_id)
        await update.message.reply_text(
            "Mi scusi, non sono riuscito a scaricare il file. "
            "Riprovi tra qualche istante o chiami il 800.99.00.90."
        )
        return

    await _process_with_typing(
        update, context, text, update.effective_user.first_name, image_bytes=image_bytes
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/aiuto command — show help."""
    if update.message is None:
        return
    await update.message.reply_text(
        "Sono l'assistente di ameconviene.it.\n\n"
        "Comandi disponibili:\n"
        "/start — Inizia una nuova conversazione\n"
        "/nuova — Chiudi sessione attuale e ricomincia\n"
        "/aiuto — Mostra questo messaggio\n"
        "/operatore — Parla con un consulente\n"
        "/elimina_dati — Richiedi cancellazione dati\n"
        "/i_miei_dati — Visualizza i tuoi dati\n\n"
        "Oppure chiami il numero verde 800.99.00.90"
    )


async def operator_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/operatore command — request human escalation."""
    if update.message is None:
        return
    await update.message.reply_text(
        "La metto in contatto con un consulente di Primo Network.\n\n"
        "Può chiamare il numero verde 800.99.00.90 (lun-ven 9-18)\n"
        "oppure scrivere a info@primonetwork.it.\n\n"
        "Un operatore la ricontatterà al più presto."
    )


async def _find_user_by_telegram_id(db: object, telegram_id: str) -> User | None:
    """Find a user by their Telegram ID."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))  # type: ignore[union-attr]
    return result.scalar_one_or_none()


async def _check_existing_deletion_request(db: object, user_id: object) -> DataDeletionRequest | None:
    """Check for an existing pending deletion request."""
    result = await db.execute(  # type: ignore[union-attr]
        select(DataDeletionRequest)
        .where(
            DataDeletionRequest.user_id == user_id,
            DataDeletionRequest.status == DeletionRequestStatus.PENDING.value,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def elimina_dati_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/elimina_dati — request data deletion (GDPR Art. 17)."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = str(update.effective_user.id)

    async with async_session_factory() as db:
        user = await _find_user_by_telegram_id(db, telegram_id)
        if user is None or user.anonymized:
            await update.message.reply_text(
                "Non risultano dati associati al suo account."
            )
            return

        # Check for existing pending request
        existing = await _check_existing_deletion_request(db, user.id)
        if existing is not None:
            await update.message.reply_text(
                "Una richiesta di cancellazione e' gia' in corso.\n"
                "Sara' elaborata al piu' presto."
            )
            return

    # Ask for confirmation
    context.user_data["awaiting_deletion_confirm"] = True  # type: ignore[index]
    await update.message.reply_text(
        "Attenzione: questa operazione e' irreversibile.\n\n"
        "Verranno eliminati:\n"
        "- Tutte le conversazioni e i messaggi\n"
        "- Documenti caricati e dati estratti\n"
        "- Calcoli, verifiche di idoneita' e preventivi\n"
        "- Dati personali (nome, contatti, codice fiscale)\n\n"
        "Saranno conservati solo i registri di consenso e audit "
        "(obbligo normativo, 5 anni).\n\n"
        "Per confermare, scriva CONFERMO.\n"
        "Per annullare, scriva qualsiasi altra cosa."
    )


async def i_miei_dati_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/i_miei_dati — view personal data summary (GDPR Art. 15)."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = str(update.effective_user.id)

    async with async_session_factory() as db:
        user = await _find_user_by_telegram_id(db, telegram_id)
        if user is None or user.anonymized:
            await update.message.reply_text(
                "Non risultano dati associati al suo account."
            )
            return

        # Get consent status
        consent_status = await consent_manager.get_consent_status(db, user.id)

        # Count sessions
        session_count_result = await db.execute(
            select(func.count(Session.id)).where(Session.user_id == user.id)
        )
        session_count = session_count_result.scalar() or 0

    # Build summary
    consent_labels = {
        "privacy_policy": "Privacy policy",
        "data_processing": "Trattamento dati",
        "marketing": "Marketing",
        "third_party": "Terze parti",
    }
    consent_lines = []
    for key, label in consent_labels.items():
        status = consent_status.get(key, False)
        icon = "Si'" if status else "No"
        consent_lines.append(f"  - {label}: {icon}")

    reg_date = user.created_at.strftime("%d/%m/%Y") if user.created_at else "N/D"

    await update.message.reply_text(
        "I suoi dati presso ameconviene.it:\n\n"
        f"Nome: {user.first_name or 'N/D'} {user.last_name or ''}\n"
        f"Canale: {user.channel}\n"
        f"Registrazione: {reg_date}\n"
        f"Sessioni: {session_count}\n\n"
        "Consensi:\n"
        + "\n".join(consent_lines)
        + "\n\n"
        "Per richiedere la cancellazione dei dati: /elimina_dati\n"
        "Per assistenza: privacy@primonetwork.it"
    )


def create_telegram_app() -> Application:
    """Build and configure the Telegram bot application.

    Returns the Application instance (not yet started).
    """
    token = settings.telegram.telegram_user_bot_token
    if not token:
        msg = "TELEGRAM_USER_BOT_TOKEN not set in environment"
        raise ValueError(msg)

    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("nuova", nuova_command))
    app.add_handler(CommandHandler("aiuto", help_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("operatore", operator_command))
    app.add_handler(CommandHandler("elimina_dati", elimina_dati_command))
    app.add_handler(CommandHandler("i_miei_dati", i_miei_dati_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot application created")
    return app
