"""Pydantic schemas for the Agenzia delle Entrate P.IVA validation API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, field_validator


class PivaValidationRequest(BaseModel):
    """Input for P.IVA validation — normalized 11-digit string."""

    piva: str  # 11-digit string, no spaces

    @field_validator("piva")
    @classmethod
    def normalize_piva(cls, v: str) -> str:
        """Strip whitespace and uppercase."""
        return v.strip().upper()


class PivaValidationResult(BaseModel):
    """Result from AdE API (or cache)."""

    valid: bool
    denomination: str | None = None  # ragione sociale from AdE response
    activity_start: date | None = None
    raw_response: dict = {}
