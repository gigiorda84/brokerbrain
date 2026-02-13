"""Tests for the CdQ (Cessione del Quinto) calculator.

Tests cover:
- CdQ capacity for dipendenti (CdQ + Delega)
- CdQ capacity for pensionati (CdQ only)
- Existing deductions reduce available capacity
- Renewal eligibility (40% rule)
- First-CdQ exception (60 → 120 months)
- Age at maturity check for pensionati
"""

from __future__ import annotations

from decimal import Decimal

from src.calculators.cdq import (
    calculate_age_at_maturity,
    calculate_cdq_capacity,
    check_cdq_renewal,
    check_pensionato_age_limit,
)


class TestCdqCapacity:
    """Test CdQ/Delega capacity calculation."""

    def test_dipendente_basic(self) -> None:
        """Dipendente with €1750 net → max CdQ €350, max Delega €350."""
        result = calculate_cdq_capacity(Decimal("1750"))
        assert result.max_cdq_rata == Decimal("350.00")
        assert result.max_delega_rata == Decimal("350.00")
        assert result.total_max == Decimal("700.00")
        assert result.available_cdq == Decimal("350.00")
        assert result.available_delega == Decimal("350.00")
        assert result.total_available == Decimal("700.00")

    def test_dipendente_with_existing_cdq(self) -> None:
        """Existing CdQ of €200 reduces available CdQ to €150."""
        result = calculate_cdq_capacity(
            Decimal("1750"),
            existing_cdq=Decimal("200"),
        )
        assert result.max_cdq_rata == Decimal("350.00")
        assert result.existing_cdq == Decimal("200.00")
        assert result.available_cdq == Decimal("150.00")
        assert result.total_used == Decimal("200.00")
        assert result.total_available == Decimal("500.00")

    def test_dipendente_with_existing_cdq_and_delega(self) -> None:
        """Existing CdQ + Delega should be subtracted from total available."""
        result = calculate_cdq_capacity(
            Decimal("1750"),
            existing_cdq=Decimal("200"),
            existing_delega=Decimal("150"),
        )
        assert result.total_used == Decimal("350.00")
        assert result.total_available == Decimal("350.00")

    def test_dipendente_maxed_out(self) -> None:
        """When existing equals max, available should be zero."""
        result = calculate_cdq_capacity(
            Decimal("1750"),
            existing_cdq=Decimal("350"),
            existing_delega=Decimal("350"),
        )
        assert result.available_cdq == Decimal("0.00")
        assert result.available_delega == Decimal("0.00")
        assert result.total_available == Decimal("0.00")

    def test_pensionato_no_delega(self) -> None:
        """Pensionati get CdQ only, no Delega."""
        result = calculate_cdq_capacity(
            Decimal("1200"),
            is_pensionato=True,
        )
        assert result.max_cdq_rata == Decimal("240.00")
        assert result.max_delega_rata == Decimal("0.00")
        assert result.total_max == Decimal("240.00")
        assert result.available_delega == Decimal("0.00")

    def test_pensionato_with_existing_cdq(self) -> None:
        """Pensionato with existing CdQ."""
        result = calculate_cdq_capacity(
            Decimal("1200"),
            existing_cdq=Decimal("100"),
            is_pensionato=True,
        )
        assert result.available_cdq == Decimal("140.00")
        assert result.total_available == Decimal("140.00")

    def test_decimal_precision(self) -> None:
        """Amounts that don't divide evenly should round correctly."""
        result = calculate_cdq_capacity(Decimal("1333"))
        assert result.max_cdq_rata == Decimal("266.60")

    def test_zero_income(self) -> None:
        """Zero income → zero capacity."""
        result = calculate_cdq_capacity(Decimal("0"))
        assert result.max_cdq_rata == Decimal("0.00")
        assert result.total_max == Decimal("0.00")


class TestCdqRenewal:
    """Test CdQ renewal eligibility."""

    def test_eligible_at_40_percent(self) -> None:
        """Exactly 40% paid → eligible."""
        result = check_cdq_renewal(total_installments=100, paid_installments=40)
        assert result.eligible is True
        assert result.paid_percentage == Decimal("40.00")

    def test_eligible_above_40_percent(self) -> None:
        """Above 40% → eligible."""
        result = check_cdq_renewal(total_installments=120, paid_installments=60)
        assert result.eligible is True
        assert result.paid_percentage == Decimal("50.00")

    def test_not_eligible_below_40(self) -> None:
        """Below 40% → not eligible."""
        result = check_cdq_renewal(total_installments=120, paid_installments=30)
        assert result.eligible is False
        assert result.paid_percentage == Decimal("25.00")

    def test_first_cdq_60_month_exception(self) -> None:
        """First CdQ at 60 months can extend to 120 without 40% rule."""
        result = check_cdq_renewal(
            total_installments=60,
            paid_installments=5,  # Only 8.3% paid
            is_first_cdq=True,
            original_duration=60,
        )
        assert result.eligible is True
        assert "60 mesi" in result.reason

    def test_first_cdq_non_60_no_exception(self) -> None:
        """First CdQ at 120 months does NOT get the 60→120 exception."""
        result = check_cdq_renewal(
            total_installments=120,
            paid_installments=10,  # 8.3%
            is_first_cdq=True,
            original_duration=120,
        )
        assert result.eligible is False

    def test_zero_installments(self) -> None:
        """Zero total installments → invalid."""
        result = check_cdq_renewal(total_installments=0, paid_installments=0)
        assert result.eligible is False


class TestAgeAtMaturity:
    """Test age at maturity calculations."""

    def test_basic_calculation(self) -> None:
        assert calculate_age_at_maturity(40, 120) == 50

    def test_partial_year(self) -> None:
        """Months that don't make a full year are truncated."""
        assert calculate_age_at_maturity(40, 119) == 49

    def test_pensionato_within_limit(self) -> None:
        """70-year-old with 120 months → 80, within 85 limit."""
        ok, age = check_pensionato_age_limit(70, 120)
        assert ok is True
        assert age == 80

    def test_pensionato_exceeds_limit(self) -> None:
        """78-year-old with 120 months → 88, exceeds 85 limit."""
        ok, age = check_pensionato_age_limit(78, 120)
        assert ok is False
        assert age == 88

    def test_pensionato_at_limit(self) -> None:
        """75-year-old with 120 months → exactly 85."""
        ok, age = check_pensionato_age_limit(75, 120)
        assert ok is True
        assert age == 85
