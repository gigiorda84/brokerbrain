"""Redis-backed fixed-window rate limiter.

Uses INCR + EXPIRE for simple, performant rate limiting.
Checks happen early in channel handlers, before any DB or LLM work.

Usage:
    from src.security.rate_limiter import rate_limiter

    allowed, retry_after = await rate_limiter.check("rate:12345:msg", limit=15, window=60)
"""

from __future__ import annotations

import logging

from src.db.engine import redis_client

logger = logging.getLogger(__name__)


class RateLimiter:
    """Fixed-window rate limiter backed by Redis INCR + EXPIRE."""

    def __init__(self, redis: object) -> None:
        self._redis = redis

    async def check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Check if a request is within the rate limit.

        Args:
            key: Redis key (e.g. "rate:{user_id}:msg").
            limit: Max requests allowed in the window.
            window: Window size in seconds.

        Returns:
            (allowed, retry_after) — allowed is True if under limit,
            retry_after is seconds until window resets (0 if allowed).
        """
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, window)

            if count > limit:
                ttl = await self._redis.ttl(key)
                retry_after = max(ttl, 1)
                return False, retry_after

            return True, 0
        except Exception:
            logger.exception("Rate limiter Redis error for key %s", key)
            # Fail open — don't block users if Redis is down
            return True, 0


# Module-level singleton
rate_limiter = RateLimiter(redis_client)
