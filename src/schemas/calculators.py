"""Pydantic schemas for calculator and decoder results.

Pure data classes — no business logic. Used as return types by
decoders (CF, ATECO) and calculators (CdQ, DTI, income).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CfResult(BaseModel):
    """Result of decoding an Italian codice fiscale."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    birthdate: date
    age: int
    gender: str  # "M" or "F"
    birthplace_code: str
    birthplace_name: str
    valid: bool


class CdqCapacity(BaseModel):
    """CdQ and Delega capacity for a given net income."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    net_income: Decimal
    max_cdq_rata: Decimal
    existing_cdq: Decimal
    available_cdq: Decimal
    max_delega_rata: Decimal
    existing_delega: Decimal
    available_delega: Decimal


class CdqRenewalResult(BaseModel):
    """Result of a CdQ renewal eligibility check."""

    eligible: bool
    paid_percentage: Decimal
    reason: str


class DtiResult(BaseModel):
    """Debt-to-income ratio calculation result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    monthly_income: Decimal
    total_obligations: Decimal
    proposed_installment: Decimal
    current_dti: Decimal
    projected_dti: Decimal
    risk_level: str  # GREEN / YELLOW / ORANGE / RED / CRITICAL


class IncomeResult(BaseModel):
    """Normalized monthly income result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    monthly_net: Decimal
    source: str
    notes: str | None = None


class AtecoResult(BaseModel):
    """ATECO code lookup result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    code: str
    description: str
    coefficient: Decimal
