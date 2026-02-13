"""Tests for the ATECO → forfettario coefficient decoder.

Tests cover:
- Known ATECO ranges (manufacturing, commerce, professional services)
- Dot-separated codes (e.g. "62.01")
- Default fallback for unknown codes
- Invalid input handling
"""

from __future__ import annotations

from decimal import Decimal

from src.decoders.ateco import lookup_ateco


class TestAtecoLookup:
    """Test ATECO code → coefficient lookup."""

    def test_manufacturing(self) -> None:
        """ATECO 10-33 (manifattura) → 0.86 coefficient."""
        result = lookup_ateco("25.11")
        assert result.coefficient == Decimal("0.86")
        assert result.matched_range == "10-33"

    def test_commerce_retail(self) -> None:
        """ATECO 47 (commercio al dettaglio) → 0.40 coefficient."""
        result = lookup_ateco("47.11")
        assert result.coefficient == Decimal("0.40")
        assert result.matched_range == "47"

    def test_professional_services(self) -> None:
        """ATECO 69-75 (professionale) → 0.78 coefficient."""
        result = lookup_ateco("69.20")
        assert result.coefficient == Decimal("0.78")
        assert result.matched_range == "69-75"

    def test_it_services(self) -> None:
        """ATECO 58-63 (IT/communication) → 0.67 coefficient."""
        result = lookup_ateco("62.01")
        assert result.coefficient == Decimal("0.67")
        assert result.matched_range == "58-63"

    def test_construction(self) -> None:
        """ATECO 41-43 (costruzioni) → 0.86 coefficient."""
        result = lookup_ateco("43.21")
        assert result.coefficient == Decimal("0.86")
        assert result.matched_range == "41-43"

    def test_hospitality(self) -> None:
        """ATECO 55-56 (alloggio/ristorazione) → 0.40 coefficient."""
        result = lookup_ateco("56.10")
        assert result.coefficient == Decimal("0.40")
        assert result.matched_range == "55-56"

    def test_healthcare(self) -> None:
        """ATECO 86-88 (sanità) → 0.78 coefficient."""
        result = lookup_ateco("86.10")
        assert result.coefficient == Decimal("0.78")
        assert result.matched_range == "86-88"

    def test_agriculture(self) -> None:
        """ATECO 01-03 (agricoltura) → 0.40 coefficient."""
        result = lookup_ateco("01.11")
        assert result.coefficient == Decimal("0.40")
        assert result.matched_range == "01-03"

    def test_default_for_unknown_range(self) -> None:
        """Unknown numeric range → default 0.67 coefficient."""
        result = lookup_ateco("00.00")
        assert result.coefficient == Decimal("0.67")
        assert result.matched_range is None

    def test_dot_separated_code(self) -> None:
        """Dot-separated ATECO codes should be handled correctly."""
        result = lookup_ateco("62.01.00")
        assert result.coefficient == Decimal("0.67")
        assert result.matched_range == "58-63"

    def test_invalid_code(self) -> None:
        """Non-numeric code → default coefficient."""
        result = lookup_ateco("XX.YY")
        assert result.coefficient == Decimal("0.67")
        assert result.matched_range is None

    def test_empty_code(self) -> None:
        """Empty string → default coefficient."""
        result = lookup_ateco("")
        assert result.coefficient == Decimal("0.67")

    def test_preserves_original_code(self) -> None:
        """The original ATECO code is preserved in the result."""
        result = lookup_ateco("69.20.13")
        assert result.ateco_code == "69.20.13"
