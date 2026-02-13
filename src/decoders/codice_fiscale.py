"""Italian Codice Fiscale (CF) decoder.

Pure Python — no LLM, no DB. Extracts birthdate, age, gender, and birthplace
from the 16-character Italian tax code.

CF format: AAABBB 00C00 D000 E
  - AAA:  surname consonants (then vowels, then X)
  - BBB:  name consonants (then vowels, then X)
  - 00:   year of birth (last 2 digits)
  - C:    month of birth (letter A–T, non-sequential)
  - 00:   day of birth (1–31 male, 41–71 female)
  - D000: birthplace code (codice catastale / Belfiore)
  - E:    check character

Reference: DPR 605/1973, Decreto MEF 12/03/1974.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from src.schemas.eligibility import CfResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CF_PATTERN = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$")

MONTH_MAP: dict[str, int] = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "H": 6,
    "L": 7, "M": 8, "P": 9, "R": 10, "S": 11, "T": 12,
}

# Checksum tables per Decreto MEF 12/03/1974
ODD_VALUES: dict[str, int] = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15,
    "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15,
    "H": 17, "I": 19, "J": 21, "K": 2, "L": 4, "M": 18, "N": 20,
    "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14, "U": 16,
    "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}

EVEN_VALUES: dict[str, int] = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9,
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6,
    "H": 7, "I": 8, "J": 9, "K": 10, "L": 11, "M": 12, "N": 13,
    "O": 14, "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19, "U": 20,
    "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
}

# Path to cadastral codes data
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CADASTRAL_CODES_PATH = _DATA_DIR / "cadastral_codes.json"


# ---------------------------------------------------------------------------
# Cadastral codes loader (cached)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_cadastral_codes() -> dict[str, str]:
    """Load the Belfiore code → municipality name mapping."""
    if not _CADASTRAL_CODES_PATH.exists():
        return {}
    with open(_CADASTRAL_CODES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("codes", {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_cf_format(cf: str) -> bool:
    """Check that the CF matches the expected 16-character pattern."""
    return bool(_CF_PATTERN.match(cf.upper().strip()))


def validate_cf_checksum(cf: str) -> bool:
    """Validate the check character (position 16) of a codice fiscale."""
    cf = cf.upper().strip()
    if len(cf) != 16:
        return False
    total = 0
    for i in range(15):
        char = cf[i]
        if i % 2 == 0:  # odd position (1-indexed)
            total += ODD_VALUES.get(char, 0)
        else:  # even position (1-indexed)
            total += EVEN_VALUES.get(char, 0)
    expected = chr(65 + (total % 26))
    return cf[15] == expected


def decode_cf(cf: str) -> CfResult:
    """Decode an Italian codice fiscale into personal data.

    Args:
        cf: The 16-character codice fiscale string.

    Returns:
        CfResult with birthdate, age, gender, birthplace, and validity.
    """
    cf_clean = cf.upper().strip()

    # Format validation
    if not validate_cf_format(cf_clean):
        return CfResult(
            valid=False,
            codice_fiscale=cf_clean,
            error="Formato non valido: il codice fiscale deve essere di 16 caratteri alfanumerici",
        )

    # Checksum validation
    if not validate_cf_checksum(cf_clean):
        return CfResult(
            valid=False,
            codice_fiscale=cf_clean,
            error="Carattere di controllo non valido",
        )

    # Extract year (positions 6–7)
    year_part = int(cf_clean[6:8])

    # Extract month (position 8)
    month_char = cf_clean[8]
    month = MONTH_MAP.get(month_char)
    if month is None:
        return CfResult(
            valid=False,
            codice_fiscale=cf_clean,
            error=f"Lettera mese non valida: {month_char}",
        )

    # Extract day and gender (positions 9–10)
    day_raw = int(cf_clean[9:11])
    if day_raw > 40:
        gender = "F"
        day = day_raw - 40
    else:
        gender = "M"
        day = day_raw

    if day < 1 or day > 31:
        return CfResult(
            valid=False,
            codice_fiscale=cf_clean,
            error=f"Giorno di nascita non valido: {day}",
        )

    # Infer century: if 2-digit year > current year's last 2 digits, assume 1900s
    today = date.today()
    current_century_cutoff = today.year % 100
    if year_part > current_century_cutoff:
        year = 1900 + year_part
    else:
        year = 2000 + year_part

    # Build birthdate
    try:
        birthdate = date(year, month, day)
    except ValueError:
        return CfResult(
            valid=False,
            codice_fiscale=cf_clean,
            error=f"Data di nascita non valida: {year}-{month:02d}-{day:02d}",
        )

    # Calculate age
    age = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        age -= 1

    # Extract birthplace code (positions 11–15)
    birthplace_code = cf_clean[11:15]
    cadastral_codes = _load_cadastral_codes()
    birthplace_name = cadastral_codes.get(birthplace_code)

    return CfResult(
        valid=True,
        codice_fiscale=cf_clean,
        birthdate=birthdate,
        age=age,
        gender=gender,
        birthplace_code=birthplace_code,
        birthplace_name=birthplace_name,
    )
