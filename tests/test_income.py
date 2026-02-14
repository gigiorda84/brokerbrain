"""Tests for the income normalizer."""

from __future__ import annotations

from decimal import Decimal

from src.calculators.income import normalize_income


class TestNormalizeIncome:
    def test_dipendente_passthrough(self) -> None:
        result = normalize_income("DIPENDENTE", Decimal("1750"))
        assert result.monthly_net == Decimal("1750.00")
        assert "Stipendio" in result.source
        assert result.notes is None

    def test_partita_iva_forfettario(self) -> None:
        # €80,000 revenue, ATECO 62.01 (coefficient 0.40)
        # Taxable: 80000 × 0.40 = 32000
        # Net: 32000 × 0.80 = 25600
        # Monthly: 25600 / 12 ≈ 2133.33
        result = normalize_income("PARTITA_IVA", Decimal("80000"), ateco_code="62.01")
        assert result.monthly_net == Decimal("2133.33")
        assert "forfettario" in result.source

    def test_partita_iva_ordinario(self) -> None:
        # Annual net income €48,000 / 12 = €4,000
        result = normalize_income("PARTITA_IVA", Decimal("48000"))
        assert result.monthly_net == Decimal("4000.00")
        assert "ordinario" in result.source

    def test_pensionato_passthrough(self) -> None:
        result = normalize_income("PENSIONATO", Decimal("1200"))
        assert result.monthly_net == Decimal("1200.00")
        assert "Pensione" in result.source

    def test_disoccupato_passthrough(self) -> None:
        result = normalize_income("DISOCCUPATO", Decimal("800"))
        assert result.monthly_net == Decimal("800.00")
        assert "NASpI" in result.source

    def test_below_minimum_generates_note(self) -> None:
        result = normalize_income("DIPENDENTE", Decimal("200"))
        assert result.notes is not None
        assert "inferiore" in result.notes

    def test_above_maximum_generates_note(self) -> None:
        result = normalize_income("DIPENDENTE", Decimal("20000"))
        assert result.notes is not None
        assert "superiore" in result.notes

    def test_within_bounds_no_note(self) -> None:
        result = normalize_income("DIPENDENTE", Decimal("2000"))
        assert result.notes is None

    def test_case_insensitive(self) -> None:
        result = normalize_income("dipendente", Decimal("1750"))
        assert result.monthly_net == Decimal("1750.00")

    def test_unknown_employment_type(self) -> None:
        result = normalize_income("CONTRATTO_ATIPICO", Decimal("1500"))
        assert result.monthly_net == Decimal("1500.00")
        assert result.notes is not None
        assert "non riconosciuto" in result.notes

    def test_forfettario_with_manufacturing_ateco(self) -> None:
        # €50,000 revenue, ATECO 25.10 (coefficient 0.86 — manifattura)
        # Taxable: 50000 × 0.86 = 43000
        # Net: 43000 × 0.80 = 34400
        # Monthly: 34400 / 12 ≈ 2866.67
        result = normalize_income("PARTITA_IVA", Decimal("50000"), ateco_code="25.10")
        assert result.monthly_net == Decimal("2866.67")
