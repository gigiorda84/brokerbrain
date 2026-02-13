"""Cessione del Quinto (CdQ) and Delega calculator.

Pure Python, Decimal arithmetic. Implements:
- CdQ/Delega capacity (max rata = 1/5 of net income)
- CdQ renewal eligibility (40% rule, DPR 180/1950)
- Age at maturity check (max 85 for pensionati)

Business rules from Primo Network / DPR 180/1950:
- CdQ rata max = net_income / 5
- Delega rata max = net_income / 5 (dipendenti only, separate quota)
- CdQ + Delega combined max = 2/5 of net (dipendenti only)
- Pensionati: CdQ only, no Delega; max age 85 at loan maturity
- Renewal: must have paid >= 40% of installments
- Exception: first CdQ at 60 months can extend to 120 months
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from src.schemas.eligibility import CdqCapacity, CdqRenewalResult


def _to_euro(value: Decimal) -> Decimal:
    """Round to 2 decimal places, Italian banking convention."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_cdq_capacity(
    net_income: Decimal,
    existing_cdq: Decimal = Decimal("0"),
    existing_delega: Decimal = Decimal("0"),
    is_pensionato: bool = False,
) -> CdqCapacity:
    """Calculate CdQ and Delega capacity for a given net income.

    Args:
        net_income: Monthly net income (salary or pension).
        existing_cdq: Current CdQ monthly installment already in place.
        existing_delega: Current Delega monthly installment already in place.
        is_pensionato: If True, Delega is not available (pensionati only get CdQ).

    Returns:
        CdqCapacity with max, existing, and available amounts.
    """
    max_cdq = _to_euro(net_income / 5)

    if is_pensionato:
        # Pensionati: only CdQ, no Delega
        max_delega = Decimal("0")
        total_max = max_cdq
    else:
        # Dipendenti: CdQ + Delega, each up to 1/5
        max_delega = _to_euro(net_income / 5)
        total_max = _to_euro(net_income * 2 / 5)

    available_cdq = _to_euro(max(Decimal("0"), max_cdq - existing_cdq))
    available_delega = _to_euro(max(Decimal("0"), max_delega - existing_delega))
    total_used = _to_euro(existing_cdq + existing_delega)
    total_available = _to_euro(max(Decimal("0"), total_max - total_used))

    return CdqCapacity(
        net_income=_to_euro(net_income),
        max_cdq_rata=max_cdq,
        existing_cdq=_to_euro(existing_cdq),
        available_cdq=available_cdq,
        max_delega_rata=max_delega,
        existing_delega=_to_euro(existing_delega),
        available_delega=available_delega,
        total_max=total_max,
        total_used=total_used,
        total_available=total_available,
    )


def check_cdq_renewal(
    total_installments: int,
    paid_installments: int,
    is_first_cdq: bool = False,
    original_duration: int | None = None,
) -> CdqRenewalResult:
    """Check CdQ renewal eligibility per DPR 180/1950.

    Args:
        total_installments: Total number of installments in the loan.
        paid_installments: Number of installments already paid.
        is_first_cdq: Whether this is the customer's first CdQ.
        original_duration: Original loan duration in months (for first-CdQ exception).

    Returns:
        CdqRenewalResult with eligibility and reasoning.
    """
    if total_installments <= 0:
        return CdqRenewalResult(
            eligible=False,
            paid_percentage=Decimal("0"),
            threshold=Decimal("40"),
            reason="Numero rate totali non valido",
        )

    paid_pct = _to_euro(Decimal(str(paid_installments)) / Decimal(str(total_installments)) * 100)

    # Exception: first CdQ at 60 months can be renegotiated to 120 months
    if is_first_cdq and original_duration is not None and original_duration == 60:
        threshold = Decimal("0")
        return CdqRenewalResult(
            eligible=True,
            paid_percentage=paid_pct,
            threshold=threshold,
            reason="Prima cessione a 60 mesi: rinegoziabile a 120 mesi senza vincolo del 40%",
        )

    # Standard rule: must have paid >= 40%
    threshold = Decimal("40")
    if paid_pct >= threshold:
        return CdqRenewalResult(
            eligible=True,
            paid_percentage=paid_pct,
            threshold=threshold,
            reason=f"Idoneo al rinnovo: {paid_pct}% delle rate pagate (soglia: 40%)",
        )

    remaining_pct = _to_euro(threshold - paid_pct)
    return CdqRenewalResult(
        eligible=False,
        paid_percentage=paid_pct,
        threshold=threshold,
        reason=f"Non ancora idoneo: {paid_pct}% pagato, manca {remaining_pct}% per raggiungere il 40%",
    )


def calculate_age_at_maturity(current_age: int, duration_months: int) -> int:
    """Calculate age at loan maturity.

    For CdQ pensionati the maximum age at maturity is 85.

    Args:
        current_age: Current age of the borrower.
        duration_months: Loan duration in months.

    Returns:
        Age at maturity.
    """
    return current_age + (duration_months // 12)


def check_pensionato_age_limit(
    current_age: int,
    duration_months: int,
    max_age: int = 85,
) -> tuple[bool, int]:
    """Check if a pensionato's age at maturity exceeds the limit.

    Args:
        current_age: Current age of the pensionato.
        duration_months: Proposed loan duration in months.
        max_age: Maximum allowed age at maturity (default 85).

    Returns:
        Tuple of (within_limit, age_at_maturity).
    """
    age_at_maturity = calculate_age_at_maturity(current_age, duration_months)
    return age_at_maturity <= max_age, age_at_maturity
