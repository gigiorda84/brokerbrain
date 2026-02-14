"""Tests for the DTI (Debt-to-Income) calculator."""

from __future__ import annotations

from decimal import Decimal

from src.calculators.dti import calculate_dti


class TestCalculateDti:
    def test_no_obligations(self) -> None:
        result = calculate_dti(Decimal("2000"), [])
        assert result.current_dti == Decimal("0.0000")
        assert result.projected_dti == Decimal("0.0000")
        assert result.risk_level == "GREEN"

    def test_green_threshold(self) -> None:
        # 600/2000 = 0.30 → GREEN
        result = calculate_dti(Decimal("2000"), [Decimal("600")])
        assert result.current_dti == Decimal("0.3000")
        assert result.risk_level == "GREEN"

    def test_yellow_threshold(self) -> None:
        # 700/2000 = 0.35 → YELLOW
        result = calculate_dti(Decimal("2000"), [Decimal("700")])
        assert result.current_dti == Decimal("0.3500")
        assert result.risk_level == "YELLOW"

    def test_orange_threshold(self) -> None:
        # 800/2000 = 0.40 → ORANGE
        result = calculate_dti(Decimal("2000"), [Decimal("800")])
        assert result.current_dti == Decimal("0.4000")
        assert result.risk_level == "ORANGE"

    def test_red_threshold(self) -> None:
        # 1000/2000 = 0.50 → RED
        result = calculate_dti(Decimal("2000"), [Decimal("1000")])
        assert result.current_dti == Decimal("0.5000")
        assert result.risk_level == "RED"

    def test_critical_threshold(self) -> None:
        # 1200/2000 = 0.60 → CRITICAL
        result = calculate_dti(Decimal("2000"), [Decimal("1200")])
        assert result.current_dti == Decimal("0.6000")
        assert result.risk_level == "CRITICAL"

    def test_between_green_and_yellow(self) -> None:
        # 620/2000 = 0.31 → YELLOW (above 0.30)
        result = calculate_dti(Decimal("2000"), [Decimal("620")])
        assert result.risk_level == "YELLOW"

    def test_proposed_installment(self) -> None:
        # Current: 500/2000 = 0.25 (GREEN)
        # Projected: (500+300)/2000 = 0.40 (ORANGE)
        result = calculate_dti(Decimal("2000"), [Decimal("500")], proposed=Decimal("300"))
        assert result.current_dti == Decimal("0.2500")
        assert result.projected_dti == Decimal("0.4000")
        assert result.risk_level == "ORANGE"  # Based on projected

    def test_multiple_obligations(self) -> None:
        obligations = [Decimal("200"), Decimal("150"), Decimal("100")]
        result = calculate_dti(Decimal("2000"), obligations)
        assert result.total_obligations == Decimal("450")
        assert result.current_dti == Decimal("0.2250")
        assert result.risk_level == "GREEN"

    def test_zero_income(self) -> None:
        result = calculate_dti(Decimal("0"), [Decimal("500")])
        assert result.current_dti == Decimal("9.9999")
        assert result.projected_dti == Decimal("9.9999")
        assert result.risk_level == "CRITICAL"

    def test_negative_income(self) -> None:
        result = calculate_dti(Decimal("-100"), [Decimal("500")])
        assert result.risk_level == "CRITICAL"

    def test_stores_proposed(self) -> None:
        result = calculate_dti(Decimal("2000"), [], proposed=Decimal("300"))
        assert result.proposed_installment == Decimal("300")
