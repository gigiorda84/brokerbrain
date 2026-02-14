"""Per-product eligibility rule functions.

Each function takes a UserProfile and returns a ProductMatchResult with full
condition tracking. Pure Python, deterministic — uses existing calculators.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from src.calculators.cdq import calculate_cdq_capacity, max_duration_for_age
from src.calculators.dti import calculate_dti
from src.eligibility.products import (
    CDQ_PENSIONE_SUBTYPES,
    CDQ_STIPENDIO_SUBTYPES,
    DELEGA_SUBTYPES,
    PRODUCT_DISPLAY_NAMES,
    ProductType,
)
from src.models.enums import EmploymentType, LiabilityType
from src.schemas.eligibility import (
    EstimatedTerms,
    ProductMatchResult,
    RuleCondition,
    UserProfile,
)


def _obligations_from_profile(profile: UserProfile) -> list[Decimal]:
    """Extract monthly obligation amounts from liabilities."""
    return [li.monthly_installment for li in profile.liabilities]


def _existing_cdq(profile: UserProfile) -> Decimal:
    """Sum of existing CdQ monthly installments."""
    return sum(
        (li.monthly_installment for li in profile.liabilities if li.type == LiabilityType.CDQ),
        Decimal("0"),
    )


def _existing_delega(profile: UserProfile) -> Decimal:
    """Sum of existing Delega monthly installments."""
    return sum(
        (li.monthly_installment for li in profile.liabilities if li.type == LiabilityType.DELEGA),
        Decimal("0"),
    )


def _first_failed_hard(conditions: list[RuleCondition]) -> str | None:
    """Return description of first failed hard condition, or None."""
    for c in conditions:
        if c.is_hard and not c.met:
            return c.description
    return None


# ── CdQ Stipendio ──────────────────────────────────────────────────────────


def check_cdq_stipendio(profile: UserProfile) -> ProductMatchResult:
    """Cessione del Quinto su Stipendio."""
    conditions: list[RuleCondition] = []
    product = ProductType.CDQ_STIPENDIO

    # Hard: must be dipendente
    is_dipendente = profile.employment_type == EmploymentType.DIPENDENTE
    conditions.append(RuleCondition(
        name="employment_type",
        description="Il richiedente deve essere un lavoratore dipendente",
        met=is_dipendente,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    # Hard: employer category known
    has_category = profile.employer_category is not None
    conditions.append(RuleCondition(
        name="employer_category",
        description="La categoria del datore di lavoro deve essere specificata",
        met=has_category,
        is_hard=True,
        value=profile.employer_category.value if profile.employer_category else None,
    ))

    # CdQ capacity
    capacity = calculate_cdq_capacity(
        profile.net_monthly_income,
        existing_cdq=_existing_cdq(profile),
    )
    has_capacity = capacity.available_cdq > 0
    conditions.append(RuleCondition(
        name="cdq_capacity",
        description="Deve esserci capacità residua per la cessione del quinto",
        met=has_capacity,
        is_hard=True,
        value=f"€{capacity.available_cdq}",
    ))

    # Soft: private employer ≥16 employees
    if profile.employer_category and profile.employer_category.value == "privato":
        big_enough = (profile.employer_size_employees or 0) >= 16
        conditions.append(RuleCondition(
            name="employer_size",
            description="Per dipendenti privati, l'azienda dovrebbe avere almeno 16 dipendenti",
            met=big_enough,
            is_hard=False,
            value=str(profile.employer_size_employees) if profile.employer_size_employees else None,
        ))

    eligible = all(c.met for c in conditions if c.is_hard)
    sub_type = CDQ_STIPENDIO_SUBTYPES.get(profile.employer_category) if profile.employer_category else None

    terms = None
    if eligible:
        max_dur = max_duration_for_age(profile.age)
        terms = EstimatedTerms(
            max_installment=capacity.available_cdq,
            max_duration_months=max_dur,
            notes=f"Rata massima CdQ: €{capacity.available_cdq}/mese, durata max {max_dur} mesi",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        sub_type=sub_type,
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── CdQ Pensione ──────────────────────────────────────────────────────────


def check_cdq_pensione(profile: UserProfile) -> ProductMatchResult:
    """Cessione del Quinto su Pensione."""
    conditions: list[RuleCondition] = []
    product = ProductType.CDQ_PENSIONE

    is_pensionato = profile.employment_type == EmploymentType.PENSIONATO
    conditions.append(RuleCondition(
        name="employment_type",
        description="Il richiedente deve essere un pensionato",
        met=is_pensionato,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    has_source = profile.pension_source is not None
    conditions.append(RuleCondition(
        name="pension_source",
        description="La cassa pensionistica deve essere specificata",
        met=has_source,
        is_hard=True,
        value=profile.pension_source.value if profile.pension_source else None,
    ))

    capacity = calculate_cdq_capacity(
        profile.net_monthly_income,
        existing_cdq=_existing_cdq(profile),
    )
    has_capacity = capacity.available_cdq > 0
    conditions.append(RuleCondition(
        name="cdq_capacity",
        description="Deve esserci capacità residua per la cessione del quinto",
        met=has_capacity,
        is_hard=True,
        value=f"€{capacity.available_cdq}",
    ))

    max_dur = max_duration_for_age(profile.age)
    has_duration = max_dur > 0
    conditions.append(RuleCondition(
        name="max_duration",
        description="L'età deve consentire una durata minima del finanziamento (max 85 anni)",
        met=has_duration,
        is_hard=True,
        value=f"{max_dur} mesi",
    ))

    eligible = all(c.met for c in conditions if c.is_hard)
    sub_type = CDQ_PENSIONE_SUBTYPES.get(profile.pension_source) if profile.pension_source else None

    terms = None
    if eligible:
        terms = EstimatedTerms(
            max_installment=capacity.available_cdq,
            max_duration_months=max_dur,
            notes=f"Rata massima CdQ: €{capacity.available_cdq}/mese, durata max {max_dur} mesi",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        sub_type=sub_type,
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Delega ─────────────────────────────────────────────────────────────────


def check_delega(profile: UserProfile) -> ProductMatchResult:
    """Delegazione di Pagamento."""
    conditions: list[RuleCondition] = []
    product = ProductType.DELEGA

    is_dipendente = profile.employment_type == EmploymentType.DIPENDENTE
    conditions.append(RuleCondition(
        name="employment_type",
        description="Il richiedente deve essere un lavoratore dipendente",
        met=is_dipendente,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    has_category = profile.employer_category is not None
    conditions.append(RuleCondition(
        name="employer_category",
        description="La categoria del datore di lavoro deve essere specificata",
        met=has_category,
        is_hard=True,
        value=profile.employer_category.value if profile.employer_category else None,
    ))

    capacity = calculate_cdq_capacity(
        profile.net_monthly_income,
        existing_delega=_existing_delega(profile),
    )
    has_capacity = capacity.available_delega > 0
    conditions.append(RuleCondition(
        name="delega_capacity",
        description="Deve esserci capacità residua per la delegazione di pagamento",
        met=has_capacity,
        is_hard=True,
        value=f"€{capacity.available_delega}",
    ))

    # Soft: employer allows delega
    if profile.employer_allows_delega is not None:
        conditions.append(RuleCondition(
            name="employer_allows_delega",
            description="Il datore di lavoro dovrebbe accettare la delegazione di pagamento",
            met=profile.employer_allows_delega,
            is_hard=False,
            value=str(profile.employer_allows_delega),
        ))

    eligible = all(c.met for c in conditions if c.is_hard)
    sub_type = DELEGA_SUBTYPES.get(profile.employer_category) if profile.employer_category else None

    terms = None
    if eligible:
        max_dur = max_duration_for_age(profile.age)
        terms = EstimatedTerms(
            max_installment=capacity.available_delega,
            max_duration_months=max_dur,
            notes=f"Rata massima Delega: €{capacity.available_delega}/mese",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        sub_type=sub_type,
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Prestito Personale ────────────────────────────────────────────────────


def check_prestito_personale(profile: UserProfile) -> ProductMatchResult:
    """Prestito Personale."""
    conditions: list[RuleCondition] = []
    product = ProductType.PRESTITO_PERSONALE

    min_income = Decimal("800")
    has_income = profile.net_monthly_income >= min_income
    conditions.append(RuleCondition(
        name="min_income",
        description=f"Il reddito netto mensile deve essere almeno €{min_income}",
        met=has_income,
        is_hard=True,
        value=f"€{profile.net_monthly_income}",
    ))

    dti = calculate_dti(profile.net_monthly_income, _obligations_from_profile(profile))
    dti_ok = dti.current_dti <= Decimal("0.40")
    conditions.append(RuleCondition(
        name="dti",
        description="Il rapporto debiti/reddito non deve superare il 40%",
        met=dti_ok,
        is_hard=True,
        value=f"{dti.current_dti * 100:.1f}%",
    ))

    # Soft: disoccupato needs guarantor
    if profile.employment_type == EmploymentType.DISOCCUPATO:
        conditions.append(RuleCondition(
            name="guarantor_needed",
            description="Per i disoccupati è consigliata la presenza di un garante",
            met=False,
            is_hard=False,
            value="Garante necessario",
        ))

    eligible = all(c.met for c in conditions if c.is_hard)

    terms = None
    if eligible:
        terms = EstimatedTerms(
            notes="Importi e tassi da verificare in base al profilo creditizio",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Mutuo Acquisto ─────────────────────────────────────────────────────────


def check_mutuo_acquisto(profile: UserProfile) -> ProductMatchResult:
    """Mutuo Acquisto."""
    conditions: list[RuleCondition] = []
    product = ProductType.MUTUO_ACQUISTO

    min_income = Decimal("1000")
    has_income = profile.net_monthly_income >= min_income
    conditions.append(RuleCondition(
        name="min_income",
        description=f"Il reddito netto mensile deve essere almeno €{min_income}",
        met=has_income,
        is_hard=True,
        value=f"€{profile.net_monthly_income}",
    ))

    dti = calculate_dti(profile.net_monthly_income, _obligations_from_profile(profile))
    dti_ok = dti.current_dti <= Decimal("0.35")
    conditions.append(RuleCondition(
        name="dti",
        description="Il rapporto debiti/reddito non deve superare il 35%",
        met=dti_ok,
        is_hard=True,
        value=f"{dti.current_dti * 100:.1f}%",
    ))

    not_disoccupato = profile.employment_type != EmploymentType.DISOCCUPATO
    conditions.append(RuleCondition(
        name="employment",
        description="Il richiedente non deve essere disoccupato",
        met=not_disoccupato,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    eligible = all(c.met for c in conditions if c.is_hard)

    terms = None
    if eligible:
        terms = EstimatedTerms(
            notes="Importi e durata da verificare con perizia immobiliare",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Mutuo Surroga ─────────────────────────────────────────────────────────


def check_mutuo_surroga(profile: UserProfile) -> ProductMatchResult:
    """Mutuo Surroga."""
    conditions: list[RuleCondition] = []
    product = ProductType.MUTUO_SURROGA

    has_mutuo = any(li.type == LiabilityType.MUTUO for li in profile.liabilities)
    conditions.append(RuleCondition(
        name="existing_mutuo",
        description="Il richiedente deve avere un mutuo in corso",
        met=has_mutuo,
        is_hard=True,
        value="Sì" if has_mutuo else "No",
    ))

    min_income = Decimal("1000")
    has_income = profile.net_monthly_income >= min_income
    conditions.append(RuleCondition(
        name="min_income",
        description=f"Il reddito netto mensile deve essere almeno €{min_income}",
        met=has_income,
        is_hard=True,
        value=f"€{profile.net_monthly_income}",
    ))

    not_disoccupato = profile.employment_type != EmploymentType.DISOCCUPATO
    conditions.append(RuleCondition(
        name="employment",
        description="Il richiedente non deve essere disoccupato",
        met=not_disoccupato,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    eligible = all(c.met for c in conditions if c.is_hard)

    terms = None
    if eligible:
        terms = EstimatedTerms(
            notes="Surroga a costo zero — condizioni da verificare con la banca",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Mutuo Consolidamento ──────────────────────────────────────────────────


def check_mutuo_consolidamento(profile: UserProfile) -> ProductMatchResult:
    """Mutuo Consolidamento Debiti."""
    conditions: list[RuleCondition] = []
    product = ProductType.MUTUO_CONSOLIDAMENTO

    num_liabilities = len(profile.liabilities)
    has_multiple = num_liabilities >= 2
    conditions.append(RuleCondition(
        name="multiple_debts",
        description="Il richiedente deve avere almeno 2 finanziamenti in corso",
        met=has_multiple,
        is_hard=True,
        value=str(num_liabilities),
    ))

    dti = calculate_dti(profile.net_monthly_income, _obligations_from_profile(profile))
    high_dti = dti.current_dti > Decimal("0.30")
    conditions.append(RuleCondition(
        name="dti_threshold",
        description="Il rapporto debiti/reddito deve superare il 30% (altrimenti non conviene consolidare)",
        met=high_dti,
        is_hard=True,
        value=f"{dti.current_dti * 100:.1f}%",
    ))

    not_disoccupato = profile.employment_type != EmploymentType.DISOCCUPATO
    conditions.append(RuleCondition(
        name="employment",
        description="Il richiedente non deve essere disoccupato",
        met=not_disoccupato,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    eligible = all(c.met for c in conditions if c.is_hard)

    terms = None
    if eligible:
        terms = EstimatedTerms(
            notes=f"Consolidamento di {num_liabilities} finanziamenti — DTI attuale {dti.current_dti * 100:.1f}%",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Anticipo TFS ──────────────────────────────────────────────────────────


def check_anticipo_tfs(profile: UserProfile) -> ProductMatchResult:
    """Anticipo TFS/TFR."""
    conditions: list[RuleCondition] = []
    product = ProductType.ANTICIPO_TFS

    is_pensionato = profile.employment_type == EmploymentType.PENSIONATO
    conditions.append(RuleCondition(
        name="employment_type",
        description="Il richiedente deve essere un pensionato",
        met=is_pensionato,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    is_ex_public = profile.ex_public_employee
    conditions.append(RuleCondition(
        name="ex_public_employee",
        description="Il richiedente deve essere un ex dipendente pubblico",
        met=is_ex_public,
        is_hard=True,
        value="Sì" if is_ex_public else "No",
    ))

    eligible = all(c.met for c in conditions if c.is_hard)

    terms = None
    if eligible:
        terms = EstimatedTerms(
            notes="Anticipo fino all'80% del TFS/TFR maturato — importo da verificare con certificazione INPS",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Credito Assicurativo ──────────────────────────────────────────────────


def check_credito_assicurativo(
    profile: UserProfile,
    other_eligible_count: int = 0,
) -> ProductMatchResult:
    """Credito Assicurativo — eligible only if at least one other product is eligible."""
    conditions: list[RuleCondition] = []
    product = ProductType.CREDITO_ASSICURATIVO

    not_disoccupato = profile.employment_type != EmploymentType.DISOCCUPATO
    conditions.append(RuleCondition(
        name="employment",
        description="Il richiedente non deve essere disoccupato",
        met=not_disoccupato,
        is_hard=True,
        value=profile.employment_type.value,
    ))

    has_other = other_eligible_count >= 1
    conditions.append(RuleCondition(
        name="other_products",
        description="Il richiedente deve essere idoneo per almeno un altro prodotto",
        met=has_other,
        is_hard=True,
        value=str(other_eligible_count),
    ))

    eligible = all(c.met for c in conditions if c.is_hard)

    terms = None
    if eligible:
        terms = EstimatedTerms(
            notes="Polizza accessoria al finanziamento — condizioni legate al prodotto principale",
        )

    return ProductMatchResult(
        product_name=PRODUCT_DISPLAY_NAMES[product],
        eligible=eligible,
        conditions=conditions,
        estimated_terms=terms,
        ineligibility_reason=_first_failed_hard(conditions) if not eligible else None,
    )


# ── Rule registry ─────────────────────────────────────────────────────────

# Maps ProductType → check function. Credito Assicurativo is excluded because
# it has a special signature (needs other_eligible_count).
RULE_CHECKS: dict[ProductType, Callable[[UserProfile], ProductMatchResult]] = {
    ProductType.CDQ_STIPENDIO: check_cdq_stipendio,
    ProductType.CDQ_PENSIONE: check_cdq_pensione,
    ProductType.DELEGA: check_delega,
    ProductType.PRESTITO_PERSONALE: check_prestito_personale,
    ProductType.MUTUO_ACQUISTO: check_mutuo_acquisto,
    ProductType.MUTUO_SURROGA: check_mutuo_surroga,
    ProductType.MUTUO_CONSOLIDAMENTO: check_mutuo_consolidamento,
    ProductType.ANTICIPO_TFS: check_anticipo_tfs,
}
