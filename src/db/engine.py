"""Async database engine, session factory, and lifespan management.

Uses SQLAlchemy 2.0 async with asyncpg driver for PostgreSQL.
Redis client for session state and pub/sub.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import settings

if TYPE_CHECKING:
    pass

# ── Async PostgreSQL engine ──────────────────────────────────────────

engine: AsyncEngine = create_async_engine(
    settings.db.database_url,
    echo=settings.log_level == "DEBUG",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# ── Session factory ──────────────────────────────────────────────────

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI — yields an async DB session.

    Usage:
        @app.get("/example")
        async def handler(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis client ─────────────────────────────────────────────────────

redis_client: aioredis.Redis = aioredis.from_url(
    settings.db.redis_url,
    decode_responses=True,
)


# ── Lifespan helpers ─────────────────────────────────────────────────


async def init_db() -> None:
    """Initialize database connection pool.

    Called during FastAPI lifespan startup. In production, tables are
    created via Alembic migrations — this only verifies connectivity.
    """
    async with engine.begin() as conn:
        # Import here to ensure all models are registered with Base.metadata
        from src.models.base import Base  # noqa: F401

        # In development, optionally create tables (prefer Alembic in production)
        if not settings.is_production:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose database engine and Redis connections.

    Called during FastAPI lifespan shutdown.
    """
    await engine.dispose()
    await redis_client.aclose()


@contextlib.asynccontextmanager
async def db_lifespan() -> AsyncGenerator[None, None]:
    """Context manager for database lifecycle.

    Usage in FastAPI lifespan:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with db_lifespan():
                yield
    """
    await init_db()
    try:
        yield
    finally:
        await close_db()
