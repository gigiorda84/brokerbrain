"""Tests for the Codice Fiscale decoder."""

from __future__ import annotations

from datetime import date

import pytest

from src.decoders.codice_fiscale import decode_cf, validate_cf_checksum


class TestValidateCfChecksum:
    def test_valid_cf(self) -> None:
        # Mario Rossi, born 12/06/1985 in Milano
        assert validate_cf_checksum("RSSMRA85H12F205Y") is True

    def test_invalid_checksum(self) -> None:
        # Same CF with wrong check letter
        assert validate_cf_checksum("RSSMRA85H12F205X") is False

    def test_too_short(self) -> None:
        assert validate_cf_checksum("RSSMRA85") is False


class TestDecodeCf:
    def test_valid_male_cf(self) -> None:
        # Mario Rossi, M, 12/06/1985, Milano (checksum=Y)
        result = decode_cf("RSSMRA85H12F205Y")
        assert result.valid is True
        assert result.gender == "M"
        assert result.birthdate == date(1985, 6, 12)
        assert result.birthplace_code == "F205"
        assert result.birthplace_name == "Milano"
        assert result.age > 0

    def test_female_day_encoding(self) -> None:
        # Laura Bianchi, F, 12/02/1992, Roma (checksum=M)
        result = decode_cf("BNCLRA92B52H501M")
        assert result.valid is True
        assert result.gender == "F"
        assert result.birthdate.day == 12
        assert result.birthdate.month == 2
        assert result.birthplace_code == "H501"
        assert result.birthplace_name == "Roma"

    def test_invalid_checksum_returns_valid_false(self) -> None:
        # Valid format but wrong checksum
        result = decode_cf("RSSMRA85H12F205X")
        assert result.valid is False
        # Should still decode the data
        assert result.gender == "M"
        assert result.birthdate == date(1985, 6, 12)

    def test_invalid_format_too_short(self) -> None:
        with pytest.raises(ValueError, match="16 alphanumeric"):
            decode_cf("RSSMRA85")

    def test_invalid_format_special_chars(self) -> None:
        with pytest.raises(ValueError, match="16 alphanumeric"):
            decode_cf("RSSMRA85H12F20!!")

    def test_lowercase_accepted(self) -> None:
        result = decode_cf("rssmra85h12f205y")
        assert result.valid is True
        assert result.gender == "M"

    def test_omocodia_handling(self) -> None:
        # Omocodia: position 14 digit '5' replaced by letter 'R' (R→5 in map)
        # RSSMRA85H12F20RT is the omocodia version with correct checksum
        result = decode_cf("RSSMRA85H12F20RT")
        assert result.valid is True
        assert result.gender == "M"
        assert result.birthdate == date(1985, 6, 12)
        assert result.birthplace_code == "F205"
        assert result.birthplace_name == "Milano"

    def test_omocodia_normalize(self) -> None:
        from src.decoders.codice_fiscale import _normalize_omocodia

        # Position 14: 'R' normalizes back to '5'
        normalized = _normalize_omocodia("RSSMRA85H12F20RT")
        assert normalized[14] == "5"
        assert normalized[11:15] == "F205"

    def test_age_calculation(self) -> None:
        result = decode_cf("RSSMRA85H12F205Y")
        expected_age = date.today().year - 1985
        if (date.today().month, date.today().day) < (6, 12):
            expected_age -= 1
        assert result.age == expected_age
