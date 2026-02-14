"""Italian Codice Fiscale decoder.

Decodes a 16-character CF into birthdate, age, gender, and birthplace.
Handles omocodia (letter-substituted digits) and validates the mod-26 checksum.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from src.schemas.calculators import CfResult

# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

MONTH_MAP: dict[str, int] = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "H": 6,
    "L": 7, "M": 8, "P": 9, "R": 10, "S": 11, "T": 12,
}

ODD_VALUES: dict[str, int] = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15,
    "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15,
    "H": 17, "I": 19, "J": 21, "K": 2, "L": 4, "M": 18, "N": 20,
    "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14, "U": 16,
    "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}

EVEN_VALUES: dict[str, int] = {str(i): i for i in range(10)}
EVEN_VALUES.update({chr(65 + i): i for i in range(26)})

# Omocodia substitution: digit position → replacement letter
OMOCODIA_MAP: dict[str, str] = {
    "L": "0", "M": "1", "N": "2", "P": "3", "Q": "4",
    "R": "5", "S": "6", "T": "7", "U": "8", "V": "9",
}

# Positions in the CF that can be substituted under omocodia (0-indexed)
OMOCODIA_POSITIONS: list[int] = [6, 7, 9, 10, 12, 13, 14]

# ---------------------------------------------------------------------------
# Cadastral codes (loaded once at module level)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CADASTRAL_CODES: dict[str, str] = {}


def _load_cadastral_codes() -> dict[str, str]:
    global _CADASTRAL_CODES  # noqa: PLW0603
    if not _CADASTRAL_CODES:
        path = _DATA_DIR / "cadastral_codes.json"
        with open(path) as f:
            data = json.load(f)
        # Filter out metadata keys starting with "_"
        _CADASTRAL_CODES = {k: v for k, v in data.items() if not k.startswith("_")}
    return _CADASTRAL_CODES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_cf_checksum(cf: str) -> bool:
    """Validate the mod-26 check character at position 16."""
    cf = cf.upper()
    if len(cf) != 16:
        return False
    total = 0
    for i in range(15):
        ch = cf[i]
        if i % 2 == 0:  # odd position (1-indexed)
            total += ODD_VALUES.get(ch, 0)
        else:  # even position (1-indexed)
            total += EVEN_VALUES.get(ch, 0)
    expected = chr(65 + (total % 26))
    return cf[15] == expected


def decode_cf(cf: str) -> CfResult:
    """Decode an Italian codice fiscale into personal data.

    Args:
        cf: 16-character codice fiscale string.

    Returns:
        CfResult with birthdate, age, gender, birthplace info, and validity.

    Raises:
        ValueError: If the CF is not exactly 16 alphanumeric characters.
    """
    if not isinstance(cf, str):
        raise ValueError("Codice fiscale must be a string")
    cf = cf.upper().strip()
    if len(cf) != 16 or not re.match(r"^[A-Z0-9]+$", cf):
        raise ValueError(f"Invalid codice fiscale format: must be 16 alphanumeric characters, got '{cf}'")

    # Normalize omocodia before decoding
    normalized = _normalize_omocodia(cf)

    # Validate checksum on the *original* (non-normalized) CF
    valid = validate_cf_checksum(cf)

    # Extract fields from the normalized CF
    year_digits = int(normalized[6:8])
    month_letter = normalized[8]
    day_digits = int(normalized[9:11])
    birthplace_code = normalized[11:15]

    # Gender: female day is offset by 40
    if day_digits > 40:
        gender = "F"
        day = day_digits - 40
    else:
        gender = "M"
        day = day_digits

    # Month
    month = MONTH_MAP.get(month_letter)
    if month is None:
        valid = False
        month = 1  # fallback to avoid crash

    # Year: pivot at current year — assume 2000+ if ≤ current 2-digit year, else 1900+
    current_year = date.today().year
    pivot = current_year % 100
    year = 2000 + year_digits if year_digits <= pivot else 1900 + year_digits

    try:
        birthdate = date(year, month, day)
    except ValueError:
        # Invalid date components
        valid = False
        birthdate = date(1900, 1, 1)

    # Age
    today = date.today()
    age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))

    # Birthplace lookup
    codes = _load_cadastral_codes()
    birthplace_name = codes.get(birthplace_code, "Sconosciuto")

    return CfResult(
        birthdate=birthdate,
        age=age,
        gender=gender,
        birthplace_code=birthplace_code,
        birthplace_name=birthplace_name,
        valid=valid,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_omocodia(cf: str) -> str:
    """Replace omocodia letter substitutions with their digit equivalents."""
    chars = list(cf.upper())
    for pos in OMOCODIA_POSITIONS:
        if chars[pos] in OMOCODIA_MAP:
            chars[pos] = OMOCODIA_MAP[chars[pos]]
    return "".join(chars)
