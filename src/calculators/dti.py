"""Debt-to-Income ratio calculator.

Computes current and projected DTI, classifies risk level.
Takes a plain list of Decimal obligations — caller extracts amounts from models.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.schemas.calculators import DtiResult

# DTI thresholds (as decimal ratios, not percentages)
_THRESHOLDS: list[tuple[Decimal, str]] = [
    (Decimal("0.30"), "GREEN"),
    (Decimal("0.35"), "YELLOW"),
    (Decimal("0.40"), "ORANGE"),
    (Decimal("0.50"), "RED"),
]


def _classify_risk(dti: Decimal) -> str:
    """Classify DTI ratio into risk level."""
    for threshold, level in _THRESHOLDS:
        if dti <= threshold:
            return level
    return "CRITICAL"


def _to_ratio(value: Decimal) -> Decimal:
    """Round DTI ratio to 4 decimal places."""
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calculate_dti(
    net_monthly_income: Decimal,
    obligations: list[Decimal],
    proposed: Decimal = Decimal("0"),
) -> DtiResult:
    """Calculate current and projected debt-to-income ratios.

    Args:
        net_monthly_income: Monthly net income.
        obligations: List of existing monthly obligation amounts.
        proposed: Proposed new monthly installment (default 0).

    Returns:
        DtiResult with current/projected DTI and risk classification.
        Risk is based on projected DTI (includes proposed installment).
    """
    total_obligations = sum(obligations, Decimal("0"))

    if net_monthly_income <= 0:
        return DtiResult(
            monthly_income=net_monthly_income,
            total_obligations=total_obligations,
            proposed_installment=proposed,
            current_dti=Decimal("9.9999"),
            projected_dti=Decimal("9.9999"),
            risk_level="CRITICAL",
        )

    current_dti = _to_ratio(total_obligations / net_monthly_income)
    projected_dti = _to_ratio((total_obligations + proposed) / net_monthly_income)

    risk_level = _classify_risk(projected_dti)

    return DtiResult(
        monthly_income=net_monthly_income,
        total_obligations=total_obligations,
        proposed_installment=proposed,
        current_dti=current_dti,
        projected_dti=projected_dti,
        risk_level=risk_level,
    )
