"""Pydantic schemas for decoders, calculators, and eligibility engine.

Pure data classes — no DB dependencies, no LLM dependencies.
Used as inputs/outputs for the deterministic calculation pipeline.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.models.enums import EmployerCategory, EmploymentType, LiabilityType, PensionSource


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DtiThreshold(str, Enum):
    """DTI risk classification per Primo Network rules."""

    GREEN = "green"          # ≤ 30% — all products
    YELLOW = "yellow"        # 31–35% — most products
    ORANGE = "orange"        # 36–40% — CdQ ok, mutuo limited
    RED = "red"              # 41–50% — consolidamento suggested
    CRITICAL = "critical"    # > 50%


class TaxRegime(str, Enum):
    """Italian tax regime for partita IVA."""

    FORFETTARIO = "forfettario"
    ORDINARIO = "ordinario"


class ProductName(str, Enum):
    """Primo Network's 9 consumer products."""

    CDQ_STIPENDIO = "cdq_stipendio"
    CDQ_PENSIONE = "cdq_pensione"
    DELEGA = "delega"
    PRESTITO_PERSONALE = "prestito_personale"
    MUTUO_ACQUISTO = "mutuo_acquisto"
    MUTUO_SURROGA = "mutuo_surroga"
    MUTUO_CONSOLIDAMENTO = "mutuo_consolidamento"
    ANTICIPO_TFS = "anticipo_tfs"
    CREDITO_ASSICURATIVO = "credito_assicurativo"


# ---------------------------------------------------------------------------
# Codice Fiscale decoder output
# ---------------------------------------------------------------------------


class CfResult(BaseModel):
    """Result of decoding an Italian codice fiscale."""

    valid: bool
    codice_fiscale: str
    birthdate: date | None = None
    age: int | None = None
    gender: str | None = None           # "M" or "F"
    birthplace_code: str | None = None   # Belfiore code, e.g. "F205"
    birthplace_name: str | None = None   # Municipality name, e.g. "MILANO"
    error: str | None = None


# ---------------------------------------------------------------------------
# ATECO decoder output
# ---------------------------------------------------------------------------


class AtecoResult(BaseModel):
    """Result of ATECO code → forfettario coefficient lookup."""

    ateco_code: str
    description: str
    coefficient: Decimal
    matched_range: str | None = None  # e.g. "69-75"


# ---------------------------------------------------------------------------
# CdQ calculator
# ---------------------------------------------------------------------------


class CdqCapacity(BaseModel):
    """CdQ and Delega capacity for a given income."""

    net_income: Decimal
    max_cdq_rata: Decimal              # net_income / 5
    existing_cdq: Decimal
    available_cdq: Decimal             # max - existing
    max_delega_rata: Decimal           # net_income / 5 (dipendenti only)
    existing_delega: Decimal
    available_delega: Decimal          # max - existing
    total_max: Decimal                 # 2/5 of net (dipendenti) or 1/5 (pensionati)
    total_used: Decimal                # existing_cdq + existing_delega
    total_available: Decimal           # total_max - total_used


class CdqRenewalResult(BaseModel):
    """CdQ renewal eligibility check result."""

    eligible: bool
    paid_percentage: Decimal           # e.g. Decimal("42.5")
    threshold: Decimal                 # 40 (or exception)
    reason: str


# ---------------------------------------------------------------------------
# DTI calculator
# ---------------------------------------------------------------------------


class LiabilityInput(BaseModel):
    """Liability data for DTI calculation (not ORM — just the numbers)."""

    type: LiabilityType
    monthly_installment: Decimal
    remaining_months: int | None = None
    residual_amount: Decimal | None = None


class DtiResult(BaseModel):
    """Debt-to-income ratio calculation result."""

    net_monthly_income: Decimal
    total_obligations: Decimal         # sum of existing monthly installments
    proposed_installment: Decimal
    current_dti: Decimal               # percentage, e.g. Decimal("22.9")
    projected_dti: Decimal             # percentage with proposed installment
    threshold: DtiThreshold
    obligation_count: int              # number of existing liabilities


# ---------------------------------------------------------------------------
# Income normalizer
# ---------------------------------------------------------------------------


class IncomeResult(BaseModel):
    """Normalized monthly income result."""

    monthly_net: Decimal
    source_description: str            # e.g. "Busta paga netto mensile"
    employment_type: EmploymentType


# ---------------------------------------------------------------------------
# Eligibility / Product matching
# ---------------------------------------------------------------------------


class ProductMatch(BaseModel):
    """Single product eligibility evaluation result."""

    product: ProductName
    sub_type: str | None = None        # e.g. "dipendente_statale", "pensionato_inpdap"
    eligible: bool
    conditions: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    estimated_terms: dict[str, Any] = Field(default_factory=dict)
    rank: int = 0
    suggestion: str | None = None      # smart suggestion text (Italian)


class UserProfile(BaseModel):
    """Aggregated user data fed into the eligibility engine.

    Built from session data (OCR, manual, CF decode, computed).
    """

    # Identity
    age: int | None = None
    gender: str | None = None

    # Employment
    employment_type: EmploymentType
    employer_category: EmployerCategory | None = None
    pension_source: PensionSource | None = None
    is_ex_public_state: bool = False   # for Anticipo TFS
    contract_type: str | None = None   # indeterminato, determinato, collaborazione
    employment_months: int | None = None
    employer_size: int | None = None   # number of employees (private sector)

    # Income
    net_monthly_income: Decimal | None = None

    # Tax — P.IVA specific
    tax_regime: TaxRegime | None = None
    ateco_code: str | None = None
    annual_revenue: Decimal | None = None

    # Liabilities
    liabilities: list[LiabilityInput] = Field(default_factory=list)
    has_existing_mortgage: bool = False

    # CdQ specific
    existing_cdq_rata: Decimal = Field(default=Decimal("0"))
    existing_delega_rata: Decimal = Field(default=Decimal("0"))

    # Household
    nucleo_familiare: int | None = None
    percettori_reddito: int | None = None
    provincia_residenza: str | None = None
    provincia_immobile: str | None = None


class EligibilityResult(BaseModel):
    """Full eligibility evaluation output."""

    profile: UserProfile
    matches: list[ProductMatch]
    suggestions: list[str] = Field(default_factory=list)
    dti: DtiResult | None = None
    cdq_capacity: CdqCapacity | None = None
