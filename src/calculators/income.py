"""Income normalization across employment types.

Converts raw income values (annual revenue, monthly salary, etc.)
to a standardized monthly net figure for use in DTI and CdQ calculations.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.decoders.ateco import lookup_ateco
from src.schemas.calculators import IncomeResult

# Validation bounds per employment type: (min_monthly, max_monthly)
_BOUNDS: dict[str, tuple[Decimal, Decimal]] = {
    "DIPENDENTE": (Decimal("400"), Decimal("15000")),
    "PARTITA_IVA": (Decimal("200"), Decimal("50000")),
    "PENSIONATO": (Decimal("300"), Decimal("10000")),
    "DISOCCUPATO": (Decimal("0"), Decimal("2000")),
}

# Flat tax rate for forfettario regime (substitute tax + INPS approximation)
_FORFETTARIO_TAX_RATE = Decimal("0.20")


def _to_euro(value: Decimal) -> Decimal:
    """Round to 2 decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_income(
    employment_type: str,
    raw_value: Decimal,
    mensilita: int = 13,
    ateco_code: str | None = None,
) -> IncomeResult:
    """Normalize income to monthly net equivalent.

    Args:
        employment_type: One of DIPENDENTE, PARTITA_IVA, PENSIONATO, DISOCCUPATO.
        raw_value: The raw income value (meaning depends on type).
        mensilita: Number of monthly payments per year (13 or 14). Used for future extensions.
        ateco_code: ATECO code for forfettario P.IVA (triggers coefficient lookup).

    Returns:
        IncomeResult with monthly_net, source description, and optional notes.
    """
    emp = employment_type.upper().strip()
    notes: str | None = None

    if emp == "DIPENDENTE":
        # raw_value is already monthly net salary
        monthly = _to_euro(raw_value)
        source = "Stipendio netto mensile"

    elif emp == "PARTITA_IVA":
        if ateco_code:
            # Forfettario: (annual_revenue × coefficient) × (1 - tax_rate) / 12
            ateco = lookup_ateco(ateco_code)
            annual_taxable = raw_value * ateco.coefficient
            annual_net = annual_taxable * (Decimal("1") - _FORFETTARIO_TAX_RATE)
            monthly = _to_euro(annual_net / 12)
            source = f"P.IVA forfettario (ATECO {ateco_code}, coeff. {ateco.coefficient})"
        else:
            # Ordinario: raw_value is annual net income
            monthly = _to_euro(raw_value / 12)
            source = "P.IVA ordinario (reddito annuo / 12)"

    elif emp == "PENSIONATO":
        # raw_value is already monthly net pension
        monthly = _to_euro(raw_value)
        source = "Pensione netta mensile"

    elif emp == "DISOCCUPATO":
        # raw_value is monthly NASpI amount
        monthly = _to_euro(raw_value)
        source = "NASpI mensile"

    else:
        monthly = _to_euro(raw_value)
        source = f"Tipo impiego sconosciuto ({employment_type})"
        notes = "Tipo di impiego non riconosciuto, valore utilizzato come reddito mensile"

    # Bounds check
    bounds = _BOUNDS.get(emp)
    if bounds:
        lo, hi = bounds
        if monthly < lo:
            notes = f"Reddito mensile ({monthly}€) inferiore al minimo atteso ({lo}€)"
        elif monthly > hi:
            notes = f"Reddito mensile ({monthly}€) superiore al massimo atteso ({hi}€)"

    return IncomeResult(monthly_net=monthly, source=source, notes=notes)
