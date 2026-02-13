"""Income normalization — convert any employment type's income to monthly net.

Pure Python, Decimal arithmetic. Handles:
- Dipendente: already monthly net (adjust for mensilità if annual)
- P.IVA forfettario: fatturato × coefficiente_di_redditività / 12
- P.IVA ordinario: reddito_imponibile / 12
- Pensionato: already monthly net
- Disoccupato: NASpI amount (already monthly)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from src.decoders.ateco import lookup_ateco
from src.models.enums import EmploymentType
from src.schemas.eligibility import IncomeResult, TaxRegime


def _to_euro(value: Decimal) -> Decimal:
    """Round to 2 decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def monthly_equivalent(
    employment_type: EmploymentType,
    raw_value: Decimal,
    is_annual: bool = False,
    mensilita: int = 13,
    tax_regime: TaxRegime | None = None,
    ateco_code: str | None = None,
) -> IncomeResult:
    """Normalize income to monthly net equivalent.

    Args:
        employment_type: How the user is employed.
        raw_value: The income value provided (monthly net, annual revenue, etc.).
        is_annual: If True, raw_value is annual (divide by 12).
        mensilita: Number of monthly payments per year (13 or 14, for dipendenti).
            Only used when is_annual is True for dipendenti.
        tax_regime: For P.IVA: forfettario or ordinario.
        ateco_code: For P.IVA forfettario: ATECO code for coefficient lookup.

    Returns:
        IncomeResult with the normalized monthly net income.
    """
    if employment_type == EmploymentType.DIPENDENTE:
        if is_annual:
            monthly = _to_euro(raw_value / mensilita)
            desc = f"Reddito annuo / {mensilita} mensilità"
        else:
            monthly = _to_euro(raw_value)
            desc = "Stipendio netto mensile"
        return IncomeResult(
            monthly_net=monthly,
            source_description=desc,
            employment_type=employment_type,
        )

    if employment_type == EmploymentType.PENSIONATO:
        if is_annual:
            monthly = _to_euro(raw_value / 13)
            desc = "Pensione annua / 13 mensilità"
        else:
            monthly = _to_euro(raw_value)
            desc = "Pensione netta mensile"
        return IncomeResult(
            monthly_net=monthly,
            source_description=desc,
            employment_type=employment_type,
        )

    if employment_type == EmploymentType.PARTITA_IVA:
        if tax_regime == TaxRegime.FORFETTARIO:
            if ateco_code is None:
                # Default coefficient if no ATECO code provided
                coefficient = Decimal("0.67")
                desc = "Forfettario: fatturato × 0.67 / 12 (coefficiente default)"
            else:
                result = lookup_ateco(ateco_code)
                coefficient = result.coefficient
                desc = f"Forfettario: fatturato × {coefficient} / 12 ({result.description})"
            taxable = raw_value * coefficient
            monthly = _to_euro(taxable / 12)
        elif tax_regime == TaxRegime.ORDINARIO:
            # raw_value is annual taxable income (reddito imponibile)
            monthly = _to_euro(raw_value / 12)
            desc = "Ordinario: reddito imponibile / 12"
        else:
            # No regime specified — assume raw_value is annual revenue, use default
            monthly = _to_euro(raw_value * Decimal("0.67") / 12)
            desc = "P.IVA: fatturato × 0.67 / 12 (regime non specificato)"
        return IncomeResult(
            monthly_net=monthly,
            source_description=desc,
            employment_type=employment_type,
        )

    if employment_type == EmploymentType.DISOCCUPATO:
        if is_annual:
            monthly = _to_euro(raw_value / 12)
            desc = "NASpI annua / 12"
        else:
            monthly = _to_euro(raw_value)
            desc = "NASpI mensile"
        return IncomeResult(
            monthly_net=monthly,
            source_description=desc,
            employment_type=employment_type,
        )

    # MIXED or unknown → treat as provided
    monthly = _to_euro(raw_value) if not is_annual else _to_euro(raw_value / 12)
    return IncomeResult(
        monthly_net=monthly,
        source_description="Reddito dichiarato",
        employment_type=employment_type,
    )
