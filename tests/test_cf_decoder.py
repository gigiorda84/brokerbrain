"""Tests for the Codice Fiscale decoder.

Tests cover:
- Valid CF decoding (known persons)
- Checksum validation
- Gender detection (male vs female)
- Month mapping completeness
- Invalid format handling
- Invalid checksum handling
- Edge cases (century inference, leap year birthdays)
"""

from __future__ import annotations

from datetime import date

from src.decoders.codice_fiscale import decode_cf, validate_cf_checksum, validate_cf_format


class TestCfFormat:
    """Test CF format validation."""

    def test_valid_format(self) -> None:
        assert validate_cf_format("RSSMRA85H52F205C") is True

    def test_lowercase_accepted(self) -> None:
        assert validate_cf_format("rssmra85h52f205c") is True

    def test_too_short(self) -> None:
        assert validate_cf_format("RSSMRA85H52F20") is False

    def test_too_long(self) -> None:
        assert validate_cf_format("RSSMRA85H52F205XY") is False

    def test_invalid_characters(self) -> None:
        assert validate_cf_format("RSSMRA85H52F205!") is False

    def test_empty_string(self) -> None:
        assert validate_cf_format("") is False


class TestCfChecksum:
    """Test CF checksum validation."""

    def test_valid_checksum_female(self) -> None:
        # Maria Rossi, born 12 June 1985 in Milano (F205)
        cf = "RSSMRA85H52F205C"
        assert validate_cf_checksum(cf) is True

    def test_valid_checksum_male(self) -> None:
        # Marco Bianchi, born 15 March 1990 in Roma (H501)
        cf = "BNCMRC90C15H501W"
        assert validate_cf_checksum(cf) is True

    def test_invalid_checksum(self) -> None:
        # Same CF with wrong check digit
        cf = "RSSMRA85H52F205A"
        assert validate_cf_checksum(cf) is False

    def test_too_short_for_checksum(self) -> None:
        assert validate_cf_checksum("RSSMRA") is False


class TestDecodeCf:
    """Test full CF decoding."""

    def test_decode_female(self) -> None:
        result = decode_cf("RSSMRA85H52F205C")
        assert result.valid is True
        assert result.gender == "F"
        assert result.birthdate == date(1985, 6, 12)
        assert result.birthplace_code == "F205"
        assert result.age is not None
        assert result.error is None

    def test_decode_male(self) -> None:
        result = decode_cf("BNCMRC90C15H501W")
        assert result.valid is True
        assert result.gender == "M"
        assert result.birthdate == date(1990, 3, 15)
        assert result.birthplace_code == "H501"

    def test_decode_gender_female_day_offset(self) -> None:
        """Female CF has day + 40, so day 52 means born on the 12th."""
        result = decode_cf("RSSMRA85H52F205C")
        assert result.gender == "F"
        assert result.birthdate is not None
        assert result.birthdate.day == 12

    def test_decode_gender_male_day_no_offset(self) -> None:
        """Male CF has actual day of birth."""
        result = decode_cf("BNCMRC90C15H501W")
        assert result.gender == "M"
        assert result.birthdate is not None
        assert result.birthdate.day == 15

    def test_invalid_format_returns_error(self) -> None:
        result = decode_cf("INVALID")
        assert result.valid is False
        assert result.error is not None
        assert "Formato" in result.error

    def test_invalid_checksum_returns_error(self) -> None:
        result = decode_cf("RSSMRA85H52F205A")
        assert result.valid is False
        assert result.error is not None
        assert "controllo" in result.error

    def test_birthplace_lookup(self) -> None:
        """F205 should resolve to MILANO in the cadastral codes."""
        result = decode_cf("RSSMRA85H52F205C")
        assert result.birthplace_code == "F205"
        assert result.birthplace_name == "MILANO"

    def test_unknown_birthplace_code(self) -> None:
        """Unknown cadastral code should return None for birthplace_name."""
        result = decode_cf("RSSMRA85H52Z999D")
        assert result.valid is True
        assert result.birthplace_code == "Z999"
        assert result.birthplace_name is None

    def test_century_inference_old(self) -> None:
        """Year 50 should be interpreted as 1950, not 2050."""
        result = decode_cf("VRDLGI50A01L219Q")
        assert result.valid is True
        assert result.birthdate is not None
        assert result.birthdate.year == 1950

    def test_lowercase_input(self) -> None:
        result = decode_cf("rssmra85h52f205c")
        assert result.valid is True
        assert result.gender == "F"

    def test_whitespace_stripped(self) -> None:
        result = decode_cf("  RSSMRA85H52F205C  ")
        assert result.valid is True

    def test_age_calculation(self) -> None:
        """Age should be calculated from birthdate to today."""
        result = decode_cf("RSSMRA85H52F205C")
        assert result.valid is True
        assert result.age is not None
        # Born 1985, so in 2026 they'd be 40 or 41
        today = date.today()
        expected_age = today.year - 1985
        if (today.month, today.day) < (6, 12):
            expected_age -= 1
        assert result.age == expected_age

    def test_all_months_decodable(self) -> None:
        """Every month letter should be in the MONTH_MAP."""
        from src.decoders.codice_fiscale import MONTH_MAP

        expected_months = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
        assert set(MONTH_MAP.values()) == expected_months
