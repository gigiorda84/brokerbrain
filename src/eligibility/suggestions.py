"""Smart suggestion generator for the eligibility engine.

Analyzes profile and eligible matches to produce proactive Italian-language
suggestions (renewal opportunities, consolidation, cross-sell).
"""

from __future__ import annotations

from decimal import Decimal

from src.calculators.cdq import check_cdq_renewal
from src.calculators.dti import calculate_dti
from src.eligibility.products import PRODUCT_DISPLAY_NAMES, ProductType
from src.models.enums import EmployerCategory, EmploymentType, LiabilityType
from src.schemas.eligibility import ProductMatchResult, SmartSuggestion, UserProfile


def _obligations_from_profile(profile: UserProfile) -> list[Decimal]:
    """Extract monthly obligation amounts from liabilities."""
    return [li.monthly_installment for li in profile.liabilities]


def generate_suggestions(
    profile: UserProfile,
    eligible_matches: list[ProductMatchResult],
) -> list[SmartSuggestion]:
    """Generate smart suggestions based on profile and eligible products."""
    suggestions: list[SmartSuggestion] = []
    eligible_names = {m.product_name for m in eligible_matches}

    # 1. Rinnovo CdQ — existing CdQ with ≥40% paid
    _check_rinnovo_cdq(profile, eligible_names, suggestions)

    # 2. Consolidamento — high DTI + multiple debts
    _check_consolidamento(profile, eligible_names, suggestions)

    # 3. Pubblico advantage — dipendente statale/pubblico
    _check_pubblico_advantage(profile, eligible_names, suggestions)

    # 4. TFS upsell — pensionato ex-pubblico + CdQ eligible
    _check_tfs_upsell(profile, eligible_names, suggestions)

    # 5. CdQ con disguidi creditizi
    _check_cdq_credit_issues(profile, eligible_names, suggestions)

    suggestions.sort(key=lambda s: s.priority)
    return suggestions


def _check_rinnovo_cdq(
    profile: UserProfile,
    eligible_names: set[str],
    suggestions: list[SmartSuggestion],
) -> None:
    """Suggest CdQ renewal if existing CdQ has ≥40% installments paid."""
    cdq_names = {
        PRODUCT_DISPLAY_NAMES[ProductType.CDQ_STIPENDIO],
        PRODUCT_DISPLAY_NAMES[ProductType.CDQ_PENSIONE],
    }
    if not eligible_names & cdq_names:
        return

    for li in profile.liabilities:
        if li.type != LiabilityType.CDQ:
            continue
        if li.total_months and li.paid_months:
            renewal = check_cdq_renewal(li.total_months, li.paid_months)
            if renewal.eligible:
                suggestions.append(SmartSuggestion(
                    suggestion_type="rinnovo_cdq",
                    title="Rinnovo Cessione del Quinto",
                    description=(
                        f"La sua cessione del quinto attuale ha raggiunto il {renewal.paid_percentage}% "
                        f"delle rate pagate. È possibile rinnovare il finanziamento ottenendo nuova liquidità "
                        f"e potenzialmente condizioni migliori."
                    ),
                    priority=1,
                    related_products=[n for n in cdq_names if n in eligible_names],
                ))
                return  # one suggestion per profile is enough


def _check_consolidamento(
    profile: UserProfile,
    eligible_names: set[str],
    suggestions: list[SmartSuggestion],
) -> None:
    """Suggest consolidamento if DTI>30% and ≥2 liabilities."""
    if len(profile.liabilities) < 2:
        return

    dti = calculate_dti(profile.net_monthly_income, _obligations_from_profile(profile))
    if dti.current_dti <= Decimal("0.30"):
        return

    consolidamento_name = PRODUCT_DISPLAY_NAMES[ProductType.MUTUO_CONSOLIDAMENTO]
    related = [consolidamento_name] if consolidamento_name in eligible_names else []

    suggestions.append(SmartSuggestion(
        suggestion_type="consolidamento",
        title="Consolidamento Debiti",
        description=(
            f"Con {len(profile.liabilities)} finanziamenti in corso e un rapporto debiti/reddito "
            f"del {dti.current_dti * 100:.1f}%, il consolidamento potrebbe ridurre la rata mensile "
            f"complessiva e semplificare la gestione dei pagamenti."
        ),
        priority=1,
        related_products=related,
    ))


def _check_pubblico_advantage(
    profile: UserProfile,
    eligible_names: set[str],
    suggestions: list[SmartSuggestion],
) -> None:
    """Highlight public-sector CdQ advantages."""
    if profile.employment_type != EmploymentType.DIPENDENTE:
        return
    if profile.employer_category not in (EmployerCategory.STATALE, EmployerCategory.PUBBLICO):
        return

    cdq_name = PRODUCT_DISPLAY_NAMES[ProductType.CDQ_STIPENDIO]
    if cdq_name not in eligible_names:
        return

    suggestions.append(SmartSuggestion(
        suggestion_type="pubblico_advantage",
        title="Vantaggio Dipendente Pubblico",
        description=(
            "Come dipendente del settore pubblico, la cessione del quinto offre condizioni "
            "particolarmente vantaggiose: tassi agevolati, nessuna richiesta di garanzie aggiuntive "
            "e approvazione facilitata grazie alla stabilità del rapporto di lavoro."
        ),
        priority=2,
        related_products=[cdq_name],
    ))


def _check_tfs_upsell(
    profile: UserProfile,
    eligible_names: set[str],
    suggestions: list[SmartSuggestion],
) -> None:
    """Suggest TFS alongside CdQ for ex-public pensioners."""
    if profile.employment_type != EmploymentType.PENSIONATO:
        return
    if not profile.ex_public_employee:
        return

    tfs_name = PRODUCT_DISPLAY_NAMES[ProductType.ANTICIPO_TFS]
    cdq_names = {PRODUCT_DISPLAY_NAMES[ProductType.CDQ_PENSIONE]}
    if tfs_name not in eligible_names:
        return
    if not eligible_names & cdq_names:
        return

    suggestions.append(SmartSuggestion(
        suggestion_type="tfs_upsell",
        title="Anticipo TFS disponibile",
        description=(
            "Come ex dipendente pubblico in pensione, oltre alla cessione del quinto può "
            "richiedere l'anticipo del TFS/TFR. Questo permette di ottenere liquidità aggiuntiva "
            "senza incidere sulla rata della cessione."
        ),
        priority=2,
        related_products=[tfs_name] + [n for n in cdq_names if n in eligible_names],
    ))


def _check_cdq_credit_issues(
    profile: UserProfile,
    eligible_names: set[str],
    suggestions: list[SmartSuggestion],
) -> None:
    """Note that CdQ works even with credit issues."""
    if not profile.has_credit_issues:
        return

    cdq_names = {
        PRODUCT_DISPLAY_NAMES[ProductType.CDQ_STIPENDIO],
        PRODUCT_DISPLAY_NAMES[ProductType.CDQ_PENSIONE],
    }
    eligible_cdq = eligible_names & cdq_names
    if not eligible_cdq:
        return

    suggestions.append(SmartSuggestion(
        suggestion_type="cdq_credit_issues",
        title="CdQ con disguidi creditizi",
        description=(
            "La cessione del quinto è accessibile anche in presenza di segnalazioni "
            "in banche dati (CRIF, CTC). La trattenuta diretta in busta paga o cedolino "
            "riduce il rischio per l'istituto finanziario, facilitando l'approvazione."
        ),
        priority=2,
        related_products=list(eligible_cdq),
    ))
