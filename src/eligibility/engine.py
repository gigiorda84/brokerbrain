"""Eligibility engine — evaluates all products against a user profile.

Pure Python orchestrator. No DB access, no LLM calls.
The conversation handler builds the UserProfile and persists results.
"""

from __future__ import annotations

from decimal import Decimal

from src.calculators.cdq import calculate_cdq_capacity
from src.calculators.dti import calculate_dti
from src.eligibility.products import PRODUCT_DISPLAY_NAMES, ProductType
from src.eligibility.rules import (
    RULE_CHECKS,
    _existing_cdq,
    _existing_delega,
    _obligations_from_profile,
    check_credito_assicurativo,
)
from src.eligibility.suggestions import generate_suggestions
from src.schemas.eligibility import EligibilityResult, ProductMatchResult, UserProfile


def _rank_products(profile: UserProfile, matches: list[ProductMatchResult]) -> None:
    """Assign ranks to eligible products in-place.

    Priority logic:
    - CdQ first for dipendente/pensionato (rank 1)
    - Consolidamento prioritized if DTI>30% + ≥2 debts (rank 2)
    - Delega/TFS (rank 3)
    - Prestito Personale (rank 5)
    - Mutuo Acquisto/Surroga (rank 6)
    - Credito Assicurativo always last (rank 99)
    """
    dti = calculate_dti(profile.net_monthly_income, _obligations_from_profile(profile))

    for match in matches:
        if not match.eligible:
            continue

        name = match.product_name
        cdq_stip = PRODUCT_DISPLAY_NAMES[ProductType.CDQ_STIPENDIO]
        cdq_pens = PRODUCT_DISPLAY_NAMES[ProductType.CDQ_PENSIONE]
        delega = PRODUCT_DISPLAY_NAMES[ProductType.DELEGA]
        prestito = PRODUCT_DISPLAY_NAMES[ProductType.PRESTITO_PERSONALE]
        mutuo_acq = PRODUCT_DISPLAY_NAMES[ProductType.MUTUO_ACQUISTO]
        mutuo_sur = PRODUCT_DISPLAY_NAMES[ProductType.MUTUO_SURROGA]
        consolidamento = PRODUCT_DISPLAY_NAMES[ProductType.MUTUO_CONSOLIDAMENTO]
        tfs = PRODUCT_DISPLAY_NAMES[ProductType.ANTICIPO_TFS]
        assicurativo = PRODUCT_DISPLAY_NAMES[ProductType.CREDITO_ASSICURATIVO]

        if name in (cdq_stip, cdq_pens):
            match.rank = 1
        elif name == consolidamento and dti.current_dti > Decimal("0.30") and len(profile.liabilities) >= 2:
            match.rank = 2
        elif name in (delega, tfs):
            match.rank = 3
        elif name == prestito:
            match.rank = 5
        elif name in (mutuo_acq, mutuo_sur):
            match.rank = 6
        elif name == assicurativo:
            match.rank = 99
        else:
            match.rank = 10


def _build_profile_summary(profile: UserProfile) -> dict[str, object]:
    """Build a summary dict for audit/display."""
    obligations = _obligations_from_profile(profile)
    dti = calculate_dti(profile.net_monthly_income, obligations)
    capacity = calculate_cdq_capacity(
        profile.net_monthly_income,
        existing_cdq=_existing_cdq(profile),
        existing_delega=_existing_delega(profile),
    )

    return {
        "employment_type": profile.employment_type.value,
        "employer_category": profile.employer_category.value if profile.employer_category else None,
        "pension_source": profile.pension_source.value if profile.pension_source else None,
        "net_monthly_income": str(profile.net_monthly_income),
        "age": profile.age,
        "num_liabilities": len(profile.liabilities),
        "total_obligations": str(dti.total_obligations),
        "current_dti": str(dti.current_dti),
        "dti_risk_level": dti.risk_level,
        "available_cdq": str(capacity.available_cdq),
        "available_delega": str(capacity.available_delega),
        "has_credit_issues": profile.has_credit_issues,
    }


def match_products(profile: UserProfile) -> EligibilityResult:
    """Evaluate all 9 products against a user profile.

    Returns EligibilityResult with ranked matches, smart suggestions,
    and a profile summary for audit.
    """
    matches: list[ProductMatchResult] = []

    # Evaluate 8 standard products
    for _product_type, check_fn in RULE_CHECKS.items():
        result = check_fn(profile)
        matches.append(result)

    # Credito Assicurativo: depends on other results
    other_eligible = sum(1 for m in matches if m.eligible)
    assicurativo = check_credito_assicurativo(profile, other_eligible_count=other_eligible)
    matches.append(assicurativo)

    # Rank eligible products
    _rank_products(profile, matches)

    # Sort: eligible first (by rank), then ineligible
    matches.sort(key=lambda m: (not m.eligible, m.rank or 999))

    # Generate smart suggestions
    eligible_matches = [m for m in matches if m.eligible]
    suggestions = generate_suggestions(profile, eligible_matches)

    return EligibilityResult(
        matches=matches,
        suggestions=suggestions,
        profile_summary=_build_profile_summary(profile),
    )
