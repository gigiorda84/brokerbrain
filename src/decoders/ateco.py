"""ATECO code → forfettario profitability coefficient lookup.

Pure Python — loads coefficients from data/ateco_coefficients.json.
Used to convert P.IVA forfettario annual revenue into taxable income:
  reddito_imponibile = fatturato × coefficiente_di_redditività

Reference: Legge 190/2014, Art. 1, commi 54-89.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from src.schemas.eligibility import AtecoResult

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_ATECO_PATH = _DATA_DIR / "ateco_coefficients.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_ateco_data() -> dict:
    """Load ATECO coefficients from JSON."""
    if not _ATECO_PATH.exists():
        return {"ranges": {}, "default": {"description": "Non trovato", "coefficient": 0.67}}
    with open(_ATECO_PATH, encoding="utf-8") as f:
        return json.load(f)


def _parse_range(range_str: str) -> tuple[int, int]:
    """Parse a range string like '10-33' into (10, 33) or '45' into (45, 45)."""
    parts = range_str.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), int(parts[0])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup_ateco(ateco_code: str) -> AtecoResult:
    """Look up the forfettario profitability coefficient for an ATECO code.

    Args:
        ateco_code: ATECO 2007 code (e.g. "62.01", "69.20.13", "47.11").
            Only the first 2 digits are used for range matching.

    Returns:
        AtecoResult with the coefficient and description.
    """
    # Normalize: strip spaces, take first 2 digits
    clean = ateco_code.strip().replace(".", "")
    if len(clean) < 2 or not clean[:2].isdigit():
        data = _load_ateco_data()
        default = data.get("default", {})
        return AtecoResult(
            ateco_code=ateco_code,
            description=default.get("description", "Codice non valido"),
            coefficient=Decimal(str(default.get("coefficient", "0.67"))),
            matched_range=None,
        )

    code_num = int(clean[:2])
    data = _load_ateco_data()
    ranges = data.get("ranges", {})

    for range_str, info in ranges.items():
        low, high = _parse_range(range_str)
        if low <= code_num <= high:
            return AtecoResult(
                ateco_code=ateco_code,
                description=info["description"],
                coefficient=Decimal(str(info["coefficient"])),
                matched_range=range_str,
            )

    # Fallback to default
    default = data.get("default", {})
    return AtecoResult(
        ateco_code=ateco_code,
        description=default.get("description", "Altre attività"),
        coefficient=Decimal(str(default.get("coefficient", "0.67"))),
        matched_range=None,
    )
