"""P.IVA validation service — orchestrates client + Redis cache."""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from src.config import settings
from src.integrations.piva.client import ade_client
from src.integrations.piva.schemas import PivaValidationResult

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "piva:"


def _cache_key(piva: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{piva}"


async def validate_piva(piva: str, redis: aioredis.Redis) -> PivaValidationResult:
    """Validate a P.IVA number, using Redis cache to avoid redundant API calls.

    Steps:
    1. Normalize (strip spaces, uppercase)
    2. Check Redis cache (key: "piva:{piva}", TTL from settings)
    3. On cache miss: call AdEClient
    4. Cache result — even invalid ones, to avoid hammering the API on re-entry
    5. Return result
    """
    normalized = piva.strip().upper()

    # 1. Check cache
    cached_raw = await redis.get(_cache_key(normalized))
    if cached_raw:
        logger.debug("P.IVA cache hit: %s", normalized[:4])
        try:
            return PivaValidationResult.model_validate_json(cached_raw)
        except Exception:
            logger.warning("Failed to deserialize cached P.IVA result, re-fetching")

    # 2. Call API
    result = await ade_client.validate(normalized)

    # 3. Cache result (omit raw_response to keep cache lean)
    cacheable = PivaValidationResult(
        valid=result.valid,
        denomination=result.denomination,
        activity_start=result.activity_start,
        raw_response={},
    )
    try:
        await redis.setex(
            _cache_key(normalized),
            settings.piva.piva_cache_ttl,
            cacheable.model_dump_json(),
        )
    except Exception:
        logger.warning("Failed to cache P.IVA result for %s", normalized[:4])

    return result
