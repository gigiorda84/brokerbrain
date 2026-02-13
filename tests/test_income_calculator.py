"""Tests for the income normalization calculator.

Tests cover:
- Dipendente: monthly net and annual conversion
- P.IVA forfettario: revenue × ATECO coefficient / 12
- P.IVA ordinario: taxable income / 12
- Pensionato: monthly and annual
- Disoccupato: NASpI amount
"""

from __future__ import annotations

from decimal import Decimal

from src.calculators.income import monthly_equivalent
from src.models.enums import EmploymentType
from src.schemas.eligibility import TaxRegime


class TestDipendenteIncome:
    """Test dipendente income normalization."""

    def test_monthly_net(self) -> None:
        """Monthly net salary passes through."""
        result = monthly_equivalent(EmploymentType.DIPENDENTE, Decimal("1750"))
        assert result.monthly_net == Decimal("1750.00")

    def test_annual_13_mensilita(self) -> None:
        """Annual with 13 mensilità → divide by 13."""
        result = monthly_equivalent(
            EmploymentType.DIPENDENTE,
            Decimal("22750"),
            is_annual=True,
            mensilita=13,
        )
        assert result.monthly_net == Decimal("1750.00")

    def test_annual_14_mensilita(self) -> None:
        """Annual with 14 mensilità → divide by 14."""
        result = monthly_equivalent(
            EmploymentType.DIPENDENTE,
            Decimal("24500"),
            is_annual=True,
            mensilita=14,
        )
        assert result.monthly_net == Decimal("1750.00")


class TestPartitaIvaIncome:
    """Test P.IVA income normalization."""

    def test_forfettario_with_ateco(self) -> None:
        """Forfettario: revenue × coefficient / 12."""
        # ATECO 69.20 (professional services) → coefficient 0.78
        result = monthly_equivalent(
            EmploymentType.PARTITA_IVA,
            Decimal("60000"),  # annual revenue
            tax_regime=TaxRegime.FORFETTARIO,
            ateco_code="69.20",
        )
        # 60000 × 0.78 / 12 = 3900
        assert result.monthly_net == Decimal("3900.00")

    def test_forfettario_without_ateco_uses_default(self) -> None:
        """Forfettario without ATECO → default coefficient 0.67."""
        result = monthly_equivalent(
            EmploymentType.PARTITA_IVA,
            Decimal("60000"),
            tax_regime=TaxRegime.FORFETTARIO,
        )
        # 60000 × 0.67 / 12 = 3350
        assert result.monthly_net == Decimal("3350.00")

    def test_ordinario(self) -> None:
        """Ordinario: taxable income / 12."""
        result = monthly_equivalent(
            EmploymentType.PARTITA_IVA,
            Decimal("36000"),  # annual taxable
            tax_regime=TaxRegime.ORDINARIO,
        )
        assert result.monthly_net == Decimal("3000.00")

    def test_no_regime_specified(self) -> None:
        """No regime → assume forfettario with default coefficient."""
        result = monthly_equivalent(
            EmploymentType.PARTITA_IVA,
            Decimal("48000"),
        )
        # 48000 × 0.67 / 12 = 2680
        assert result.monthly_net == Decimal("2680.00")


class TestPensionatoIncome:
    """Test pensionato income normalization."""

    def test_monthly_net(self) -> None:
        result = monthly_equivalent(EmploymentType.PENSIONATO, Decimal("1200"))
        assert result.monthly_net == Decimal("1200.00")

    def test_annual(self) -> None:
        """Annual pension with 13 mensilità."""
        result = monthly_equivalent(
            EmploymentType.PENSIONATO,
            Decimal("15600"),
            is_annual=True,
        )
        assert result.monthly_net == Decimal("1200.00")


class TestDisoccupatoIncome:
    """Test disoccupato (NASpI) income normalization."""

    def test_monthly_naspi(self) -> None:
        result = monthly_equivalent(EmploymentType.DISOCCUPATO, Decimal("800"))
        assert result.monthly_net == Decimal("800.00")

    def test_annual_naspi(self) -> None:
        result = monthly_equivalent(
            EmploymentType.DISOCCUPATO,
            Decimal("9600"),
            is_annual=True,
        )
        assert result.monthly_net == Decimal("800.00")


class TestEmploymentTypeTracking:
    """Test that employment type is correctly tracked in result."""

    def test_dipendente_type(self) -> None:
        result = monthly_equivalent(EmploymentType.DIPENDENTE, Decimal("1500"))
        assert result.employment_type == EmploymentType.DIPENDENTE

    def test_pensionato_type(self) -> None:
        result = monthly_equivalent(EmploymentType.PENSIONATO, Decimal("1200"))
        assert result.employment_type == EmploymentType.PENSIONATO

    def test_mixed_type(self) -> None:
        result = monthly_equivalent(EmploymentType.MIXED, Decimal("2000"))
        assert result.employment_type == EmploymentType.MIXED
