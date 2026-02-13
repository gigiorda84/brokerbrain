"""FastAPI application entry point — wires everything together.

Usage:
    python -m src.main

Starts FastAPI (health check) + Telegram bot (long-polling) concurrently.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI

from src.admin.bot import create_admin_bot
from src.admin.events import start_event_system, stop_event_system
from src.channels.telegram import create_telegram_app
from src.config import settings
from src.db.engine import db_lifespan
from src.llm.client import llm_client

# ── Logging setup ────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    stream=sys.stdout,
)
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = logging.getLogger(__name__)

# ── FastAPI lifespan ─────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    logger.info("Starting BrokerBot (env=%s)", settings.environment)

    # 1. Database
    async with db_lifespan():
        logger.info("Database initialized")

        # 2. Event system
        await start_event_system()
        logger.info("Event system started")

        # 3. Telegram user bot — create, initialize, and start polling
        telegram_app = create_telegram_app()
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
        logger.info("Telegram user bot polling started")

        # 4. Admin bot (optional — only starts if token is configured)
        admin_app = None
        if settings.telegram.telegram_admin_bot_token:
            try:
                admin_app = create_admin_bot()
                await admin_app.initialize()
                await admin_app.start()
                await admin_app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
                logger.info("Telegram admin bot polling started")
            except Exception:
                logger.exception("Failed to start admin bot — continuing without it")
                admin_app = None

        try:
            yield
        finally:
            # Shutdown in reverse order
            logger.info("Shutting down BrokerBot...")

            # Admin bot shutdown
            if admin_app is not None:
                try:
                    if admin_app.updater:
                        await admin_app.updater.stop()
                    await admin_app.stop()
                    await admin_app.shutdown()
                    logger.info("Admin bot stopped")
                except Exception:
                    logger.exception("Error stopping admin bot")

            if telegram_app.updater:
                await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()
            logger.info("Telegram user bot stopped")

            await llm_client.close()
            logger.info("LLM client closed")

            await stop_event_system()
            logger.info("Event system stopped")

    logger.info("BrokerBot shutdown complete")


# ── FastAPI app ──────────────────────────────────────────────────────

app = FastAPI(
    title="BrokerBot API",
    description="AI-powered lead qualification for ameconviene.it",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "bot_name": settings.branding.bot_name,
    }


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
