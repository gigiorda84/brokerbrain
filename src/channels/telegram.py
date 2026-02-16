"""Telegram user bot adapter — handles incoming messages via long-polling.

Uses python-telegram-bot v21+ async. Routes messages to the conversation engine
and sends responses back to the user.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
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
from src.db.engine import async_session_factory

logger = logging.getLogger(__name__)

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
                telegram_id=telegram_id,
                text=text,
                first_name=first_name,
                image_bytes=image_bytes,
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command — begin a new qualification conversation."""
    if update.effective_user is None or update.message is None:
        return
    await _process_with_typing(update, context, "/start", update.effective_user.first_name)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — route to conversation engine."""
    if update.effective_user is None or update.message is None or update.message.text is None:
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
    app.add_handler(CommandHandler("aiuto", help_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("operatore", operator_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot application created")
    return app
