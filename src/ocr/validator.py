"""Deterministic post-extraction validation for OCR results.

Synchronous, no LLM. Validates extracted data against known rules
(CF checksums, salary ranges, date sanity, installment consistency)
and classifies fields by confidence into confirmation/admin-review buckets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from src.decoders.codice_fiscale import validate_cf_checksum
from src.models.enums import DocumentType
from src.schemas.ocr import (
    BustaPagaResult,
    CedolinoPensioneResult,
    DichiarazioneRedditiResult,
    ExtractionResult,
    LoanDocumentResult,
)

# Thresholds
ADMIN_REVIEW_THRESHOLD = 0.50
CONFIRMATION_THRESHOLD = 0.70

# Salary / pension sanity bounds
MIN_SALARY = Decimal("200")
MAX_SALARY = Decimal("50000")
MIN_INSTALLMENT = Decimal("1")
MAX_INSTALLMENT = Decimal("10000")


@dataclass
class ValidationResult:
    """Result of deterministic post-extraction validation."""

    confidence_overrides: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    fields_needing_confirmation: list[str] = field(default_factory=list)
    fields_needing_admin_review: list[str] = field(default_factory=list)


def validate_extraction(result: ExtractionResult, doc_type: DocumentType) -> ValidationResult:
    """Run all applicable validation rules on an extraction result.

    Args:
        result: The extraction result from a VLM extractor.
        doc_type: The classified document type.

    Returns:
        ValidationResult with confidence overrides, warnings, and threshold fields.
    """
    vr = ValidationResult()

    if isinstance(result, BustaPagaResult):
        _validate_busta_paga(result, vr)
    elif isinstance(result, CedolinoPensioneResult):
        _validate_cedolino(result, vr)
    elif isinstance(result, DichiarazioneRedditiResult):
        _validate_dichiarazione(result, vr)
    elif isinstance(result, LoanDocumentResult):
        _validate_loan(result, vr)

    # Apply thresholds across all confidence values
    merged = dict(result.confidence)
    merged.update(vr.confidence_overrides)
    _apply_thresholds(merged, vr)

    return vr


# ── Busta paga validation ────────────────────────────────────────────


def _validate_busta_paga(result: BustaPagaResult, vr: ValidationResult) -> None:
    _validate_cf(result.codice_fiscale, result.confidence, vr)
    _validate_salary_range(result.gross_salary, "gross_salary", vr)
    _validate_salary_range(result.net_salary, "net_salary", vr)

    if (
        result.gross_salary is not None
        and result.net_salary is not None
        and result.net_salary > result.gross_salary
    ):
        vr.warnings.append("Net salary exceeds gross salary")
        vr.confidence_overrides["net_salary"] = 0.30
        vr.confidence_overrides["gross_salary"] = 0.30

    _validate_date_field(result.hiring_date, "hiring_date", vr, min_year=1950, allow_future=False)
    _validate_period(result.pay_period, "pay_period", vr)
    _validate_deductions(result, vr)


# ── Cedolino pensione validation ─────────────────────────────────────


def _validate_cedolino(result: CedolinoPensioneResult, vr: ValidationResult) -> None:
    _validate_cf(result.codice_fiscale, result.confidence, vr)
    _validate_salary_range(result.gross_pension, "gross_pension", vr)
    _validate_salary_range(result.net_pension, "net_pension", vr)

    if (
        result.gross_pension is not None
        and result.net_pension is not None
        and result.net_pension > result.gross_pension
    ):
        vr.warnings.append("Net pension exceeds gross pension")
        vr.confidence_overrides["net_pension"] = 0.30
        vr.confidence_overrides["gross_pension"] = 0.30

    _validate_period(result.pay_period, "pay_period", vr)
    _validate_deductions_cedolino(result, vr)


# ── Dichiarazione redditi validation ─────────────────────────────────


def _validate_dichiarazione(result: DichiarazioneRedditiResult, vr: ValidationResult) -> None:
    _validate_cf(result.codice_fiscale, result.confidence, vr)

    if result.partita_iva is not None and not re.match(r"^\d{11}$", result.partita_iva):
        vr.warnings.append(f"P.IVA format invalid: {result.partita_iva}")
        vr.confidence_overrides["partita_iva"] = 0.30

    if result.ateco_code is not None and not re.match(r"^\d{2}\.\d{2}(\.\d{1,2})?$", result.ateco_code):
        vr.warnings.append(f"ATECO format invalid: {result.ateco_code}")
        vr.confidence_overrides["ateco_code"] = 0.30


# ── Loan document validation ─────────────────────────────────────────


def _validate_loan(result: LoanDocumentResult, vr: ValidationResult) -> None:
    _validate_cf(result.codice_fiscale, result.confidence, vr)

    if (
        result.monthly_installment is not None
        and not MIN_INSTALLMENT <= result.monthly_installment <= MAX_INSTALLMENT
    ):
        vr.warnings.append(f"Monthly installment out of range: {result.monthly_installment}")
        vr.confidence_overrides["monthly_installment"] = 0.30

    # Installment consistency: paid + remaining ≈ total
    if (
        result.total_installments is not None
        and result.paid_installments is not None
        and result.remaining_installments is not None
    ):
        computed_total = result.paid_installments + result.remaining_installments
        if abs(computed_total - result.total_installments) > 1:
            vr.warnings.append(
                f"Installment count mismatch: paid({result.paid_installments}) "
                f"+ remaining({result.remaining_installments}) != total({result.total_installments})"
            )
            vr.confidence_overrides["total_installments"] = 0.40
            vr.confidence_overrides["paid_installments"] = 0.40
            vr.confidence_overrides["remaining_installments"] = 0.40

    _validate_date_field(result.maturity_date, "maturity_date", vr, allow_future=True, require_future=True)


# ── Shared validation helpers ────────────────────────────────────────


def _validate_cf(cf: str | None, confidence: dict[str, float], vr: ValidationResult) -> None:
    """Validate codice fiscale checksum."""
    if cf is None:
        return
    if validate_cf_checksum(cf):
        vr.confidence_overrides["codice_fiscale"] = 1.0
    else:
        vr.warnings.append(f"CF checksum invalid: {cf}")
        vr.confidence_overrides["codice_fiscale"] = 0.30


def _validate_salary_range(
    amount: Decimal | None, field_name: str, vr: ValidationResult
) -> None:
    """Check salary/pension amount is within reasonable bounds."""
    if amount is None:
        return
    if not MIN_SALARY <= amount <= MAX_SALARY:
        vr.warnings.append(f"{field_name} out of range: {amount}")
        vr.confidence_overrides[field_name] = 0.30


def _validate_date_field(
    date_str: str | None,
    field_name: str,
    vr: ValidationResult,
    *,
    min_year: int = 1950,
    allow_future: bool = False,
    require_future: bool = False,
) -> None:
    """Validate a DD/MM/YYYY date string."""
    if date_str is None:
        return
    try:
        parsed = datetime.strptime(date_str, "%d/%m/%Y").date()
    except ValueError:
        vr.warnings.append(f"{field_name} is not a valid DD/MM/YYYY date: {date_str}")
        vr.confidence_overrides[field_name] = 0.30
        return

    today = date.today()
    if parsed.year < min_year:
        vr.warnings.append(f"{field_name} year too old: {parsed.year}")
        vr.confidence_overrides[field_name] = 0.30
    elif not allow_future and parsed > today:
        vr.warnings.append(f"{field_name} is in the future: {date_str}")
        vr.confidence_overrides[field_name] = 0.30
    elif require_future and parsed <= today:
        vr.warnings.append(f"{field_name} should be in the future: {date_str}")
        vr.confidence_overrides[field_name] = 0.40


def _validate_period(period: str | None, field_name: str, vr: ValidationResult) -> None:
    """Validate a MM/YYYY period string."""
    if period is None:
        return
    if not re.match(r"^(0[1-9]|1[0-2])/\d{4}$", period):
        vr.warnings.append(f"{field_name} is not a valid MM/YYYY period: {period}")
        vr.confidence_overrides[field_name] = 0.30


def _validate_deductions(result: BustaPagaResult, vr: ValidationResult) -> None:
    """Check deduction amounts are positive and less than net salary."""
    if result.deductions is None or result.net_salary is None:
        return
    for name, amount in [
        ("cessione_del_quinto", result.deductions.cessione_del_quinto),
        ("delegazione", result.deductions.delegazione),
        ("pignoramento", result.deductions.pignoramento),
    ]:
        if amount is not None:
            if amount <= 0:
                vr.warnings.append(f"Deduction {name} is not positive: {amount}")
                vr.confidence_overrides[f"deductions.{name}"] = 0.30
            elif amount > result.net_salary:
                vr.warnings.append(f"Deduction {name} exceeds net salary")
                vr.confidence_overrides[f"deductions.{name}"] = 0.40


def _validate_deductions_cedolino(result: CedolinoPensioneResult, vr: ValidationResult) -> None:
    """Check deduction amounts against net pension."""
    if result.deductions is None or result.net_pension is None:
        return
    for name, amount in [
        ("cessione_del_quinto", result.deductions.cessione_del_quinto),
        ("delegazione", result.deductions.delegazione),
        ("pignoramento", result.deductions.pignoramento),
    ]:
        if amount is not None:
            if amount <= 0:
                vr.warnings.append(f"Deduction {name} is not positive: {amount}")
                vr.confidence_overrides[f"deductions.{name}"] = 0.30
            elif amount > result.net_pension:
                vr.warnings.append(f"Deduction {name} exceeds net pension")
                vr.confidence_overrides[f"deductions.{name}"] = 0.40


def _apply_thresholds(confidence: dict[str, float], vr: ValidationResult) -> None:
    """Classify fields into confirmation/admin-review based on confidence thresholds."""
    for field_name, score in confidence.items():
        if score < ADMIN_REVIEW_THRESHOLD and field_name not in vr.fields_needing_admin_review:
            vr.fields_needing_admin_review.append(field_name)
        elif score < CONFIRMATION_THRESHOLD and field_name not in vr.fields_needing_confirmation:
            vr.fields_needing_confirmation.append(field_name)
