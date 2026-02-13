"""Tests for the DTI (Debt-to-Income) calculator.

Tests cover:
- Basic DTI calculation
- All threshold classifications (GREEN, YELLOW, ORANGE, RED, CRITICAL)
- Zero income edge case
- Multiple liabilities
- Projected DTI with proposed installment
"""

from __future__ import annotations

from decimal import Decimal

from src.calculators.dti import calculate_dti
from src.models.enums import LiabilityType
from src.schemas.eligibility import DtiThreshold, LiabilityInput


def _liability(amount: str, type_: LiabilityType = LiabilityType.PRESTITO) -> LiabilityInput:
    """Helper to create a LiabilityInput."""
    return LiabilityInput(type=type_, monthly_installment=Decimal(amount))


class TestDtiBasic:
    """Test basic DTI calculation."""

    def test_no_obligations(self) -> None:
        """No debts → 0% DTI."""
        result = calculate_dti(Decimal("2000"))
        assert result.current_dti == Decimal("0.00")
        assert result.projected_dti == Decimal("0.00")
        assert result.threshold == DtiThreshold.GREEN

    def test_single_obligation(self) -> None:
        """€400 obligation on €2000 income → 20% DTI."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("400")],
        )
        assert result.current_dti == Decimal("20.00")
        assert result.obligation_count == 1

    def test_multiple_obligations(self) -> None:
        """Multiple debts should be summed."""
        result = calculate_dti(
            Decimal("1750"),
            existing_obligations=[
                _liability("180"),
                _liability("220"),
            ],
        )
        assert result.total_obligations == Decimal("400.00")
        assert result.current_dti == Decimal("22.86")  # 400/1750*100

    def test_proposed_installment(self) -> None:
        """Projected DTI includes the proposed new installment."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("200")],
            proposed_installment=Decimal("300"),
        )
        assert result.current_dti == Decimal("10.00")
        assert result.projected_dti == Decimal("25.00")  # (200+300)/2000*100

    def test_none_obligations_treated_as_empty(self) -> None:
        result = calculate_dti(Decimal("1500"), existing_obligations=None)
        assert result.total_obligations == Decimal("0.00")


class TestDtiThresholds:
    """Test DTI threshold classification."""

    def test_green_threshold(self) -> None:
        """≤ 30% → GREEN."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("500")],  # 25%
        )
        assert result.threshold == DtiThreshold.GREEN

    def test_green_at_exactly_30(self) -> None:
        """Exactly 30% → GREEN."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("600")],  # 30%
        )
        assert result.threshold == DtiThreshold.GREEN

    def test_yellow_threshold(self) -> None:
        """31–35% → YELLOW."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("640")],  # 32%
        )
        assert result.threshold == DtiThreshold.YELLOW

    def test_orange_threshold(self) -> None:
        """36–40% → ORANGE."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("760")],  # 38%
        )
        assert result.threshold == DtiThreshold.ORANGE

    def test_red_threshold(self) -> None:
        """41–50% → RED."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("900")],  # 45%
        )
        assert result.threshold == DtiThreshold.RED

    def test_critical_threshold(self) -> None:
        """> 50% → CRITICAL."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("1200")],  # 60%
        )
        assert result.threshold == DtiThreshold.CRITICAL


class TestDtiEdgeCases:
    """Test edge cases."""

    def test_zero_income(self) -> None:
        """Zero income → CRITICAL (999.99%)."""
        result = calculate_dti(
            Decimal("0"),
            existing_obligations=[_liability("100")],
        )
        assert result.current_dti == Decimal("999.99")
        assert result.threshold == DtiThreshold.CRITICAL

    def test_negative_income(self) -> None:
        """Negative income → CRITICAL."""
        result = calculate_dti(
            Decimal("-500"),
            existing_obligations=[_liability("100")],
        )
        assert result.threshold == DtiThreshold.CRITICAL

    def test_threshold_based_on_projected(self) -> None:
        """Threshold classification uses projected DTI, not current."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[_liability("500")],  # current: 25% GREEN
            proposed_installment=Decimal("300"),  # projected: 40% ORANGE
        )
        assert result.current_dti == Decimal("25.00")
        assert result.projected_dti == Decimal("40.00")
        assert result.threshold == DtiThreshold.ORANGE

    def test_liability_types_tracked(self) -> None:
        """Different liability types are summed correctly."""
        result = calculate_dti(
            Decimal("2000"),
            existing_obligations=[
                _liability("200", LiabilityType.CDQ),
                _liability("150", LiabilityType.AUTO),
                _liability("100", LiabilityType.CONSUMER),
            ],
        )
        assert result.total_obligations == Decimal("450.00")
        assert result.obligation_count == 3
