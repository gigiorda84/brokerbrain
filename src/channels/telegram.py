"""Telegram user bot adapter — handles incoming messages via long-polling.

Uses python-telegram-bot v21+ async. Routes messages to the conversation engine
and sends responses back to the user.
"""

from __future__ import annotations

import logging

from telegram import Update
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command — begin a new qualification conversation."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = str(update.effective_user.id)
    first_name = update.effective_user.first_name

    async with async_session_factory() as db:
        try:
            response = await conversation_engine.process_message(
                db=db,
                telegram_id=telegram_id,
                text="/start",
                first_name=first_name,
            )
            await db.commit()
            await update.message.reply_text(response)
        except Exception:
            logger.exception("Error processing /start for user %s", telegram_id)
            await update.message.reply_text(
                "Mi scusi, si è verificato un errore. "
                "Riprovi tra qualche istante o chiami il 800.99.00.90."
            )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — route to conversation engine."""
    if update.effective_user is None or update.message is None or update.message.text is None:
        return

    telegram_id = str(update.effective_user.id)
    first_name = update.effective_user.first_name
    text = update.message.text

    async with async_session_factory() as db:
        try:
            response = await conversation_engine.process_message(
                db=db,
                telegram_id=telegram_id,
                text=text,
                first_name=first_name,
            )
            await db.commit()
            await update.message.reply_text(response)
        except Exception:
            logger.exception("Error processing message from user %s", telegram_id)
            await update.message.reply_text(
                "Mi scusi, si è verificato un errore. "
                "Riprovi tra qualche istante o chiami il 800.99.00.90."
            )


async def handle_photo_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos and image documents — download and route to conversation engine."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = str(update.effective_user.id)
    first_name = update.effective_user.first_name
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

    async with async_session_factory() as db:
        try:
            response = await conversation_engine.process_message(
                db=db,
                telegram_id=telegram_id,
                text=text,
                first_name=first_name,
                image_bytes=image_bytes,
            )
            await db.commit()
            await update.message.reply_text(response)
        except Exception:
            logger.exception("Error processing photo/document from user %s", telegram_id)
            await update.message.reply_text(
                "Mi scusi, si è verificato un errore. "
                "Riprovi tra qualche istante o chiami il 800.99.00.90."
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
