"""ATECO code → forfettario profitability coefficient lookup.

Loads coefficients from data/ateco_coefficients.json and matches
the first 2 digits of an ATECO code against defined ranges.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from src.schemas.calculators import AtecoResult

# ---------------------------------------------------------------------------
# Data loading (once at module level)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_ATECO_DATA: dict[str, dict[str, str | float]] = {}


def _load_ateco_data() -> dict[str, dict[str, str | float]]:
    global _ATECO_DATA  # noqa: PLW0603
    if not _ATECO_DATA:
        path = _DATA_DIR / "ateco_coefficients.json"
        with open(path) as f:
            _ATECO_DATA.update(json.load(f))
    return _ATECO_DATA


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup_ateco(code: str) -> AtecoResult:
    """Look up the forfettario profitability coefficient for an ATECO code.

    Extracts the first 2 digits (the "divisione") and matches against
    known ranges. Falls back to the default coefficient if no match.

    Args:
        code: ATECO 2007 code (e.g. "62.01", "62.01.00", "62").

    Returns:
        AtecoResult with code, description, and coefficient.
    """
    data = _load_ateco_data()

    # Extract first 2 digits: "62.01.00" → 62, "6" → 6
    digits = code.replace(".", "").replace(" ", "")
    prefix = int(digits[:2]) if len(digits) >= 2 else int(digits)

    # Search ranges
    for key, entry in data.items():
        if key == "default":
            continue
        if "-" in key:
            lo, hi = key.split("-")
            if int(lo) <= prefix <= int(hi):
                return AtecoResult(
                    code=code,
                    description=str(entry["description"]),
                    coefficient=Decimal(str(entry["coefficient"])),
                )
        else:
            if prefix == int(key):
                return AtecoResult(
                    code=code,
                    description=str(entry["description"]),
                    coefficient=Decimal(str(entry["coefficient"])),
                )

    # Default fallback
    default = data["default"]
    return AtecoResult(
        code=code,
        description=str(default["description"]),
        coefficient=Decimal(str(default["coefficient"])),
    )
