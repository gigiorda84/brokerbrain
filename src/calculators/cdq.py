"""Cessione del Quinto capacity, renewal eligibility, and duration calculators.

All amounts are Decimal. No LLM dependency — pure deterministic math.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.schemas.calculators import CdqCapacity, CdqRenewalResult


def to_euro(value: Decimal) -> Decimal:
    """Round to 2 decimal places using Italian banking convention."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_cdq_capacity(
    net_income: Decimal,
    existing_cdq: Decimal = Decimal("0"),
    existing_delega: Decimal = Decimal("0"),
) -> CdqCapacity:
    """Calculate CdQ and Delega capacity for a given net income.

    Max CdQ rata = net_income / 5 (1/5 rule).
    Max Delega rata = net_income / 5 (separate from CdQ).
    Available = max(0, max_rata - existing).
    """
    max_cdq = to_euro(net_income / 5)
    max_delega = to_euro(net_income / 5)
    available_cdq = max(Decimal("0"), to_euro(max_cdq - existing_cdq))
    available_delega = max(Decimal("0"), to_euro(max_delega - existing_delega))

    return CdqCapacity(
        net_income=net_income,
        max_cdq_rata=max_cdq,
        existing_cdq=existing_cdq,
        available_cdq=available_cdq,
        max_delega_rata=max_delega,
        existing_delega=existing_delega,
        available_delega=available_delega,
    )


def check_cdq_renewal(
    total_installments: int,
    paid_installments: int,
    is_first_cdq: bool = False,
) -> CdqRenewalResult:
    """Check CdQ renewal eligibility per DPR 180/1950.

    Standard rule: must have paid >= 40% of installments.
    Exception: first-time CdQ at 60 months can renegotiate to 120.
    """
    if total_installments <= 0:
        return CdqRenewalResult(
            eligible=False,
            paid_percentage=Decimal("0"),
            reason="Numero rate totali non valido",
        )

    paid_pct = to_euro(Decimal(str(paid_installments)) / Decimal(str(total_installments)) * 100)

    if is_first_cdq:
        return CdqRenewalResult(
            eligible=True,
            paid_percentage=paid_pct,
            reason="Prima CdQ: rinegoziazione da 60 a 120 mesi disponibile",
        )

    if paid_pct >= Decimal("40"):
        return CdqRenewalResult(
            eligible=True,
            paid_percentage=paid_pct,
            reason=f"Rinnovo disponibile: {paid_pct}% rate pagate (soglia 40%)",
        )

    return CdqRenewalResult(
        eligible=False,
        paid_percentage=paid_pct,
        reason=f"Rinnovo non disponibile: {paid_pct}% rate pagate (necessario almeno 40%)",
    )


def max_duration_for_age(current_age: int, max_age: int = 85) -> int:
    """Maximum CdQ duration in months given current age.

    Returns min(120, remaining_years * 12), clamped to >= 0.
    """
    remaining_months = (max_age - current_age) * 12
    return max(0, min(120, remaining_months))
