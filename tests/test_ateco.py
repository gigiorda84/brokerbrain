"""Tests for the ATECO code → forfettario coefficient lookup."""

from __future__ import annotations

from decimal import Decimal

from src.decoders.ateco import lookup_ateco


class TestLookupAteco:
    def test_known_code_services(self) -> None:
        # 62.01 (software) falls in 55-63 range
        result = lookup_ateco("62.01")
        assert result.coefficient == Decimal("0.40")
        assert result.code == "62.01"

    def test_range_match_manufacturing(self) -> None:
        # Code 25 falls in "10-43" range
        result = lookup_ateco("25")
        assert result.coefficient == Decimal("0.86")
        assert "Manifattura" in result.description

    def test_exact_match_vehicles(self) -> None:
        # Code 45 is an exact key
        result = lookup_ateco("45.11")
        assert result.coefficient == Decimal("0.40")
        assert "veicoli" in result.description.lower()

    def test_professional_services(self) -> None:
        # 69-75 range
        result = lookup_ateco("71.12")
        assert result.coefficient == Decimal("0.78")

    def test_finance_range(self) -> None:
        # 64-66 range
        result = lookup_ateco("65.00")
        assert result.coefficient == Decimal("0.78")

    def test_education(self) -> None:
        # 85 exact match
        result = lookup_ateco("85.10")
        assert result.coefficient == Decimal("0.78")

    def test_healthcare(self) -> None:
        # 86-88 range
        result = lookup_ateco("86.10")
        assert result.coefficient == Decimal("0.78")

    def test_unknown_code_returns_default(self) -> None:
        # Code 99 doesn't match any range
        result = lookup_ateco("99.99")
        assert result.coefficient == Decimal("0.67")
        assert "Altre" in result.description

    def test_commerce_range(self) -> None:
        # 46-47 range
        result = lookup_ateco("47.11")
        assert result.coefficient == Decimal("0.40")

    def test_full_ateco_code_format(self) -> None:
        # Full format: "62.01.00"
        result = lookup_ateco("62.01.00")
        assert result.coefficient == Decimal("0.40")
