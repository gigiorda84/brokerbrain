"""Pydantic schemas for OCR extraction results.

One schema per document type, plus a top-level OcrResult wrapper.
All money fields use Decimal. All schemas carry per-field confidence dicts.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import (
    ContractType,
    DocumentType,
    EmployerCategory,
    LiabilityType,
    PensionSource,
    PensionType,
    TaxRegime,
)

# ── Building blocks ──────────────────────────────────────────────────


class NamedDeduction(BaseModel):
    """A single named deduction line from a payslip or cedolino."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    description: str
    amount: Decimal


class DeductionSet(BaseModel):
    """Structured deductions extracted from a payslip or pension slip."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    cessione_del_quinto: Decimal | None = None
    delegazione: Decimal | None = None
    pignoramento: Decimal | None = None
    other: list[NamedDeduction] = Field(default_factory=list)


# ── Per-document extraction results ─────────────────────────────────


class BustaPagaResult(BaseModel):
    """Fields extracted from an Italian payslip (busta paga)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    employee_name: str | None = None
    codice_fiscale: str | None = None
    employer_name: str | None = None
    employer_category: EmployerCategory | None = None
    contract_type: ContractType | None = None
    ccnl: str | None = None
    hiring_date: str | None = None  # DD/MM/YYYY
    pay_period: str | None = None  # MM/YYYY
    ral: Decimal | None = None
    gross_salary: Decimal | None = None
    net_salary: Decimal | None = None
    tfr_accrued: Decimal | None = None
    seniority_months: int | None = None
    deductions: DeductionSet | None = None
    confidence: dict[str, float] = Field(default_factory=dict)


class CedolinoPensioneResult(BaseModel):
    """Fields extracted from an Italian pension slip (cedolino pensione)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pensioner_name: str | None = None
    codice_fiscale: str | None = None
    pension_source: PensionSource | None = None
    pension_type: PensionType | None = None
    pay_period: str | None = None  # MM/YYYY
    gross_pension: Decimal | None = None
    net_pension: Decimal | None = None
    net_pension_before_cdq: Decimal | None = None
    irpef_withheld: Decimal | None = None
    addizionale_regionale: Decimal | None = None
    deductions: DeductionSet | None = None
    confidence: dict[str, float] = Field(default_factory=dict)


class DichiarazioneRedditiResult(BaseModel):
    """Fields extracted from an Italian tax return (dichiarazione redditi)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    taxpayer_name: str | None = None
    codice_fiscale: str | None = None
    partita_iva: str | None = None
    ateco_code: str | None = None
    tax_regime: TaxRegime | None = None
    tax_year: int | None = None
    reddito_imponibile: Decimal | None = None
    reddito_lordo: Decimal | None = None
    imposta_netta: Decimal | None = None
    volume_affari: Decimal | None = None
    confidence: dict[str, float] = Field(default_factory=dict)


class LoanDocumentResult(BaseModel):
    """Fields extracted from a loan payoff statement (conteggio estintivo)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    borrower_name: str | None = None
    codice_fiscale: str | None = None
    lender_name: str | None = None
    loan_type: LiabilityType | None = None
    original_amount: Decimal | None = None
    residual_debt: Decimal | None = None
    monthly_installment: Decimal | None = None
    total_installments: int | None = None
    paid_installments: int | None = None
    remaining_installments: int | None = None
    start_date: str | None = None  # DD/MM/YYYY
    maturity_date: str | None = None  # DD/MM/YYYY
    confidence: dict[str, float] = Field(default_factory=dict)


# ── Classification ───────────────────────────────────────────────────


class ClassificationResult(BaseModel):
    """Result of document type classification."""

    doc_type: DocumentType
    confidence: float


# ── Top-level wrapper ────────────────────────────────────────────────

ExtractionResult = BustaPagaResult | CedolinoPensioneResult | DichiarazioneRedditiResult | LoanDocumentResult


class OcrResult(BaseModel):
    """Top-level OCR pipeline result returned to the caller."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    doc_type: DocumentType | None = None
    extraction_result: ExtractionResult | None = None
    overall_confidence: float = 0.0
    fields_needing_confirmation: list[str] = Field(default_factory=list)
    fields_needing_admin_review: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0
    error: str | None = None
