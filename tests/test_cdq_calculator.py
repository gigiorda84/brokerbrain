"""Tests for the CdQ capacity, renewal, and duration calculators."""

from __future__ import annotations

from decimal import Decimal

from src.calculators.cdq import calculate_cdq_capacity, check_cdq_renewal, max_duration_for_age


class TestCalculateCdqCapacity:
    def test_basic_capacity(self) -> None:
        # €1,750 net → €350 max rata
        result = calculate_cdq_capacity(Decimal("1750"))
        assert result.max_cdq_rata == Decimal("350.00")
        assert result.available_cdq == Decimal("350.00")
        assert result.max_delega_rata == Decimal("350.00")
        assert result.available_delega == Decimal("350.00")

    def test_existing_cdq_reduces_available(self) -> None:
        result = calculate_cdq_capacity(Decimal("1750"), existing_cdq=Decimal("200"))
        assert result.max_cdq_rata == Decimal("350.00")
        assert result.available_cdq == Decimal("150.00")
        # Delega unaffected
        assert result.available_delega == Decimal("350.00")

    def test_existing_delega_separate(self) -> None:
        result = calculate_cdq_capacity(
            Decimal("1750"),
            existing_cdq=Decimal("100"),
            existing_delega=Decimal("50"),
        )
        assert result.available_cdq == Decimal("250.00")
        assert result.available_delega == Decimal("300.00")

    def test_available_never_negative(self) -> None:
        result = calculate_cdq_capacity(Decimal("1750"), existing_cdq=Decimal("500"))
        assert result.available_cdq == Decimal("0")

    def test_rounding(self) -> None:
        # €1,333 / 5 = €266.60
        result = calculate_cdq_capacity(Decimal("1333"))
        assert result.max_cdq_rata == Decimal("266.60")

    def test_stores_net_income(self) -> None:
        result = calculate_cdq_capacity(Decimal("2000"))
        assert result.net_income == Decimal("2000")


class TestCheckCdqRenewal:
    def test_exactly_40_percent(self) -> None:
        # 48/120 = 40% → eligible
        result = check_cdq_renewal(120, 48)
        assert result.eligible is True
        assert result.paid_percentage == Decimal("40.00")

    def test_below_40_percent(self) -> None:
        # 47/120 ≈ 39.17% → not eligible
        result = check_cdq_renewal(120, 47)
        assert result.eligible is False
        assert result.paid_percentage < Decimal("40")

    def test_above_40_percent(self) -> None:
        result = check_cdq_renewal(120, 60)
        assert result.eligible is True
        assert result.paid_percentage == Decimal("50.00")

    def test_first_cdq_exception(self) -> None:
        # First CdQ: always eligible for renegotiation
        result = check_cdq_renewal(60, 10, is_first_cdq=True)
        assert result.eligible is True
        assert "rinegoziazione" in result.reason.lower()

    def test_zero_installments(self) -> None:
        result = check_cdq_renewal(0, 0)
        assert result.eligible is False

    def test_all_paid(self) -> None:
        result = check_cdq_renewal(120, 120)
        assert result.eligible is True
        assert result.paid_percentage == Decimal("100.00")


class TestMaxDurationForAge:
    def test_age_72(self) -> None:
        # (85 - 72) * 12 = 156, capped at 120
        assert max_duration_for_age(72) == 120

    def test_age_76(self) -> None:
        # (85 - 76) * 12 = 108
        assert max_duration_for_age(76) == 108

    def test_age_80(self) -> None:
        # (85 - 80) * 12 = 60
        assert max_duration_for_age(80) == 60

    def test_age_85(self) -> None:
        # (85 - 85) * 12 = 0
        assert max_duration_for_age(85) == 0

    def test_age_over_max(self) -> None:
        # (85 - 90) * 12 = -60, clamped to 0
        assert max_duration_for_age(90) == 0

    def test_young_capped_at_120(self) -> None:
        # (85 - 30) * 12 = 660, capped at 120
        assert max_duration_for_age(30) == 120

    def test_custom_max_age(self) -> None:
        # max_age=90: (90 - 80) * 12 = 120
        assert max_duration_for_age(80, max_age=90) == 120
