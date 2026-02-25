"""Tests for P.IVA validation client and service.

Covers:
- Valid P.IVA: AdE returns valid=True and denomination
- Invalid P.IVA: AdE returns valida=false
- Timeout: httpx.TimeoutException handled gracefully (fail open)
- Cache: second call uses Redis, does not call httpx again
- Bypass mode: empty API key skips HTTP entirely
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.piva.client import AdEClient
from src.integrations.piva.schemas import PivaValidationResult
from src.integrations.piva.service import validate_piva

# ── Helpers ──────────────────────────────────────────────────────────


def _make_response(payload: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()  # no-op for 200
    return resp


def _make_redis(cached: bytes | None = None) -> AsyncMock:
    """Build a mock aioredis.Redis that optionally returns a cached value."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached)
    redis.setex = AsyncMock()
    return redis


# ── Client tests ─────────────────────────────────────────────────────


class TestAdEClientValidPiva:
    @pytest.mark.asyncio()
    async def test_validate_valid_piva(self):
        """AdE returns valida=true with denomination — parsed correctly."""
        payload = {
            "valida": True,
            "denominazione": "ROSSI MARIO",
            "dataInizioAttivita": "2015-03-01",
        }

        client = AdEClient()
        client._api_key = "test-key"  # not bypass mode

        mock_response = _make_response(payload)

        with (
            patch("src.integrations.piva.client.emit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.validate("12345678901")

        assert result.valid is True
        assert result.denomination == "Rossi Mario"  # .title() applied
        assert result.activity_start == date(2015, 3, 1)


class TestAdEClientInvalidPiva:
    @pytest.mark.asyncio()
    async def test_validate_invalid_piva(self):
        """AdE returns valida=false — result.valid is False, no denomination."""
        payload = {"valida": False}

        client = AdEClient()
        client._api_key = "test-key"

        mock_response = _make_response(payload)

        with (
            patch("src.integrations.piva.client.emit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.validate("00000000000")

        assert result.valid is False
        assert result.denomination is None


class TestAdEClientTimeout:
    @pytest.mark.asyncio()
    async def test_validate_piva_timeout(self):
        """httpx.TimeoutException → graceful fail-open (valid=True, no denomination)."""
        client = AdEClient()
        client._api_key = "test-key"

        with (
            patch("src.integrations.piva.client.emit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.validate("12345678901")

        # Fail open — don't block the user on network issues
        assert result.valid is True
        assert result.denomination is None


class TestAdEClientBypassMode:
    @pytest.mark.asyncio()
    async def test_bypass_mode_skips_http(self):
        """Empty API key → bypass mode, valid=True without any HTTP call."""
        client = AdEClient()
        client._api_key = ""  # force bypass

        with (
            patch("src.integrations.piva.client.emit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            result = await client.validate("12345678901")

            # HTTP client must NOT be instantiated
            mock_client_cls.assert_not_called()

        assert result.valid is True
        assert result.denomination is None


# ── Service (cache) tests ─────────────────────────────────────────────


class TestPivaServiceCache:
    @pytest.mark.asyncio()
    async def test_validate_piva_cached(self):
        """Second call uses Redis cache — AdEClient.validate called only once."""
        cached_result = PivaValidationResult(valid=True, denomination="Bianchi Spa")
        cached_bytes = cached_result.model_dump_json().encode()

        redis = _make_redis(cached=cached_bytes)

        with patch("src.integrations.piva.service.ade_client") as mock_ade:
            mock_ade.validate = AsyncMock()
            result = await validate_piva("12345678901", redis)

        # AdEClient.validate must not be called because cache hit
        mock_ade.validate.assert_not_called()
        assert result.valid is True
        assert result.denomination == "Bianchi Spa"

    @pytest.mark.asyncio()
    async def test_validate_piva_cache_miss_calls_api(self):
        """Cache miss → AdEClient.validate is called and result is cached."""
        redis = _make_redis(cached=None)  # cache miss

        api_result = PivaValidationResult(valid=True, denomination="Verdi Srl")

        with patch("src.integrations.piva.service.ade_client") as mock_ade:
            mock_ade.validate = AsyncMock(return_value=api_result)
            result = await validate_piva("98765432109", redis)

        mock_ade.validate.assert_called_once_with("98765432109")
        # Result should have been stored in Redis
        redis.setex.assert_called_once()
        assert result.denomination == "Verdi Srl"

    @pytest.mark.asyncio()
    async def test_validate_piva_normalizes_input(self):
        """Input is uppercased and stripped before cache lookup."""
        cached_result = PivaValidationResult(valid=True)
        cached_bytes = cached_result.model_dump_json().encode()

        redis = _make_redis(cached=cached_bytes)

        with patch("src.integrations.piva.service.ade_client") as mock_ade:
            mock_ade.validate = AsyncMock()
            await validate_piva("  12345678901  ", redis)

        # Whitespace stripped, cache key should be "piva:12345678901"
        redis.get.assert_called_once_with("piva:12345678901")
