"""Debt-to-Income (DTI) ratio calculator.

Pure Python, Decimal arithmetic. Implements:
- Current DTI: total existing obligations / net monthly income
- Projected DTI: (existing + proposed) / net monthly income
- Threshold classification per Primo Network rules

Thresholds:
  ≤ 30%  → GREEN   (all products available)
  31–35% → YELLOW  (most products)
  36–40% → ORANGE  (CdQ still ok, mutuo limited)
  41–50% → RED     (consolidamento suggested)
  > 50%  → CRITICAL
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from src.schemas.eligibility import DtiResult, DtiThreshold, LiabilityInput


def _to_euro(value: Decimal) -> Decimal:
    """Round to 2 decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _classify_dti(dti: Decimal) -> DtiThreshold:
    """Classify a DTI percentage into a risk threshold."""
    if dti <= Decimal("30"):
        return DtiThreshold.GREEN
    if dti <= Decimal("35"):
        return DtiThreshold.YELLOW
    if dti <= Decimal("40"):
        return DtiThreshold.ORANGE
    if dti <= Decimal("50"):
        return DtiThreshold.RED
    return DtiThreshold.CRITICAL


def calculate_dti(
    net_monthly_income: Decimal,
    existing_obligations: list[LiabilityInput] | None = None,
    proposed_installment: Decimal = Decimal("0"),
) -> DtiResult:
    """Calculate current and projected debt-to-income ratio.

    Args:
        net_monthly_income: Monthly net income (post-tax).
        existing_obligations: List of existing liabilities with monthly installments.
        proposed_installment: Monthly installment of a proposed new product.

    Returns:
        DtiResult with current DTI, projected DTI, and threshold classification.
    """
    if existing_obligations is None:
        existing_obligations = []

    total_obligations = _to_euro(
        sum(
            (ob.monthly_installment for ob in existing_obligations),
            start=Decimal("0"),
        )
    )

    if net_monthly_income <= Decimal("0"):
        # Zero or negative income → maximum DTI
        return DtiResult(
            net_monthly_income=_to_euro(net_monthly_income),
            total_obligations=total_obligations,
            proposed_installment=_to_euro(proposed_installment),
            current_dti=Decimal("999.99"),
            projected_dti=Decimal("999.99"),
            threshold=DtiThreshold.CRITICAL,
            obligation_count=len(existing_obligations),
        )

    current_dti = _to_euro(total_obligations / net_monthly_income * 100)
    projected_dti = _to_euro(
        (total_obligations + proposed_installment) / net_monthly_income * 100
    )

    # Threshold is based on projected DTI (worst case)
    threshold = _classify_dti(projected_dti)

    return DtiResult(
        net_monthly_income=_to_euro(net_monthly_income),
        total_obligations=total_obligations,
        proposed_installment=_to_euro(proposed_installment),
        current_dti=current_dti,
        projected_dti=projected_dti,
        threshold=threshold,
        obligation_count=len(existing_obligations),
    )
