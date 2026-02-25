"""Async httpx client for Agenzia delle Entrate P.IVA validation API."""

from __future__ import annotations

import logging
from datetime import date

import httpx

from src.admin.events import emit
from src.config import settings
from src.integrations.piva.schemas import PivaValidationResult
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)

# AdE API response field names
_FIELD_VALID = "valida"
_FIELD_DENOMINATION = "denominazione"
_FIELD_ACTIVITY_START = "dataInizioAttivita"


class AdEClient:
    """Thin async wrapper around the Agenzia delle Entrate P.IVA verification endpoint.

    Endpoint: GET {base_url}/{piva_number}
    Auth: Ocp-Apim-Subscription-Key header
    """

    def __init__(self) -> None:
        self._base_url = settings.piva.piva_ade_api_url.rstrip("/")
        self._api_key = settings.piva.piva_ade_api_key
        self._timeout = httpx.Timeout(10.0, connect=5.0)

    @property
    def _bypass_mode(self) -> bool:
        """Return True if API key is not configured (dev/test bypass)."""
        return not self._api_key

    async def validate(self, piva: str) -> PivaValidationResult:
        """Call AdE API and return a structured result.

        In bypass mode (no API key configured) returns valid=True without making
        any HTTP request — useful for local development.
        """
        if self._bypass_mode:
            logger.debug("P.IVA validation bypass mode active (no API key configured)")
            return PivaValidationResult(valid=True, denomination=None)

        await emit(SystemEvent(
            event_type=EventType.EXTERNAL_API_CALL,
            data={"integration": "ade_piva", "piva": piva[:4] + "XXXXXXX"},  # partial mask
            source_module="integrations.piva.client",
        ))

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/{piva}",
                    headers={"Ocp-Apim-Subscription-Key": self._api_key},
                )
                response.raise_for_status()
                payload: dict = response.json()

        except httpx.TimeoutException:
            logger.warning("AdE API timeout for P.IVA %s", piva[:4])
            await emit(SystemEvent(
                event_type=EventType.EXTERNAL_API_RESPONSE,
                data={"integration": "ade_piva", "error": "timeout"},
                source_module="integrations.piva.client",
            ))
            # On timeout, return valid=True to avoid blocking the flow
            return PivaValidationResult(valid=True, denomination=None)

        except httpx.HTTPStatusError as exc:
            logger.warning("AdE API HTTP error %s for P.IVA %s", exc.response.status_code, piva[:4])
            await emit(SystemEvent(
                event_type=EventType.EXTERNAL_API_RESPONSE,
                data={"integration": "ade_piva", "error": f"http_{exc.response.status_code}"},
                source_module="integrations.piva.client",
            ))
            # On 4xx/5xx, fail open — don't block the user
            return PivaValidationResult(valid=True, denomination=None)

        result = self._parse_response(piva, payload)

        await emit(SystemEvent(
            event_type=EventType.EXTERNAL_API_RESPONSE,
            data={
                "integration": "ade_piva",
                "valid": result.valid,
                "has_denomination": result.denomination is not None,
            },
            source_module="integrations.piva.client",
        ))

        return result

    def _parse_response(self, piva: str, payload: dict) -> PivaValidationResult:
        """Parse the AdE JSON response into a PivaValidationResult."""
        valid = bool(payload.get(_FIELD_VALID, False))

        denomination: str | None = payload.get(_FIELD_DENOMINATION) or None
        if denomination:
            denomination = denomination.strip().title()

        activity_start: date | None = None
        raw_date = payload.get(_FIELD_ACTIVITY_START)
        if raw_date:
            try:
                # AdE returns ISO date string "YYYY-MM-DD"
                activity_start = date.fromisoformat(str(raw_date)[:10])
            except (ValueError, TypeError):
                logger.debug("Could not parse activity_start date: %s", raw_date)

        return PivaValidationResult(
            valid=valid,
            denomination=denomination,
            activity_start=activity_start,
            raw_response=payload,
        )


# Module-level singleton
ade_client = AdEClient()
