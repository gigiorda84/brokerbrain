"""Tests for the eligibility engine.

Each test builds a UserProfile and asserts product matches, ranks,
estimated terms, and smart suggestions.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.eligibility import match_products
from src.eligibility.products import PRODUCT_DISPLAY_NAMES, ProductType
from src.models.enums import EmployerCategory, EmploymentType, LiabilityType, PensionSource
from src.schemas.eligibility import LiabilitySnapshot, UserProfile

# Convenience aliases for display names
N = PRODUCT_DISPLAY_NAMES


def _find(result, product_type: ProductType):
    """Find a match by product type display name."""
    name = N[product_type]
    for m in result.matches:
        if m.product_name == name:
            return m
    pytest.fail(f"Product {name} not found in results")


class TestDipendentePubblicoClean:
    """Dipendente pubblico, €2000, age 40, no liabilities."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.PUBBLICO,
            net_monthly_income=Decimal("2000"),
            age=40,
        )
        return match_products(profile)

    def test_cdq_eligible(self, result):
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.eligible is True
        assert cdq.sub_type == "Dipendente Pubblico"

    def test_cdq_terms(self, result):
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.estimated_terms is not None
        assert cdq.estimated_terms.max_installment == Decimal("400.00")

    def test_delega_eligible(self, result):
        delega = _find(result, ProductType.DELEGA)
        assert delega.eligible is True

    def test_cdq_ranked_first(self, result):
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.rank == 1

    def test_assicurativo_eligible(self, result):
        assic = _find(result, ProductType.CREDITO_ASSICURATIVO)
        assert assic.eligible is True

    def test_cdq_pensione_ineligible(self, result):
        cdq_p = _find(result, ProductType.CDQ_PENSIONE)
        assert cdq_p.eligible is False

    def test_tfs_ineligible(self, result):
        tfs = _find(result, ProductType.ANTICIPO_TFS)
        assert tfs.eligible is False


class TestPensionatoRenewableCdq:
    """Pensionato INPS, €1500, age 68, existing CdQ 55/120 paid."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.PENSIONATO,
            pension_source=PensionSource.INPS,
            net_monthly_income=Decimal("1500"),
            age=68,
            liabilities=[
                LiabilitySnapshot(
                    type=LiabilityType.CDQ,
                    monthly_installment=Decimal("200"),
                    total_months=120,
                    paid_months=55,
                ),
            ],
        )
        return match_products(profile)

    def test_cdq_eligible(self, result):
        cdq = _find(result, ProductType.CDQ_PENSIONE)
        assert cdq.eligible is True
        assert cdq.sub_type == "Pensionato INPS"

    def test_rinnovo_suggestion(self, result):
        rinnovo = [s for s in result.suggestions if s.suggestion_type == "rinnovo_cdq"]
        assert len(rinnovo) == 1
        assert rinnovo[0].priority == 1

    def test_available_capacity(self, result):
        cdq = _find(result, ProductType.CDQ_PENSIONE)
        # max rata = 1500/5 = 300, existing = 200, available = 100
        assert cdq.estimated_terms is not None
        assert cdq.estimated_terms.max_installment == Decimal("100.00")


class TestHighDtiConsolidamento:
    """Dipendente privato, €2000, 2 debts totaling €750."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.PRIVATO,
            net_monthly_income=Decimal("2000"),
            age=45,
            employer_size_employees=20,
            liabilities=[
                LiabilitySnapshot(
                    type=LiabilityType.PRESTITO,
                    monthly_installment=Decimal("400"),
                ),
                LiabilitySnapshot(
                    type=LiabilityType.AUTO,
                    monthly_installment=Decimal("350"),
                ),
            ],
        )
        return match_products(profile)

    def test_consolidamento_eligible(self, result):
        consol = _find(result, ProductType.MUTUO_CONSOLIDAMENTO)
        assert consol.eligible is True

    def test_consolidamento_suggestion(self, result):
        consol_sug = [s for s in result.suggestions if s.suggestion_type == "consolidamento"]
        assert len(consol_sug) == 1
        assert consol_sug[0].priority == 1

    def test_dti_in_summary(self, result):
        # DTI = 750/2000 = 0.375
        dti = Decimal(result.profile_summary["current_dti"])
        assert dti == Decimal("0.3750")


class TestDisoccupatoLimited:
    """Disoccupato, €800 NASpI, no liabilities."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DISOCCUPATO,
            net_monthly_income=Decimal("800"),
            age=35,
        )
        return match_products(profile)

    def test_only_prestito_eligible(self, result):
        eligible = [m for m in result.matches if m.eligible]
        assert len(eligible) == 1
        assert eligible[0].product_name == N[ProductType.PRESTITO_PERSONALE]

    def test_guarantor_flagged(self, result):
        prestito = _find(result, ProductType.PRESTITO_PERSONALE)
        guarantor = [c for c in prestito.conditions if c.name == "guarantor_needed"]
        assert len(guarantor) == 1
        assert guarantor[0].met is False
        assert guarantor[0].is_hard is False

    def test_cdq_ineligible(self, result):
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.eligible is False

    def test_assicurativo_ineligible(self, result):
        assic = _find(result, ProductType.CREDITO_ASSICURATIVO)
        assert assic.eligible is False


class TestPensionatoExPubblicoTfs:
    """Pensionato INPDAP, ex-public, €2500, age 65."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.PENSIONATO,
            pension_source=PensionSource.INPDAP,
            ex_public_employee=True,
            net_monthly_income=Decimal("2500"),
            age=65,
        )
        return match_products(profile)

    def test_cdq_eligible(self, result):
        cdq = _find(result, ProductType.CDQ_PENSIONE)
        assert cdq.eligible is True
        assert cdq.sub_type == "Pensionato INPDAP"

    def test_tfs_eligible(self, result):
        tfs = _find(result, ProductType.ANTICIPO_TFS)
        assert tfs.eligible is True

    def test_tfs_upsell_suggestion(self, result):
        tfs_sug = [s for s in result.suggestions if s.suggestion_type == "tfs_upsell"]
        assert len(tfs_sug) == 1
        assert tfs_sug[0].priority == 2


class TestAge80DurationLimit:
    """Pensionato INPS, €1200, age 80 — duration capped."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.PENSIONATO,
            pension_source=PensionSource.INPS,
            net_monthly_income=Decimal("1200"),
            age=80,
        )
        return match_products(profile)

    def test_cdq_eligible(self, result):
        cdq = _find(result, ProductType.CDQ_PENSIONE)
        assert cdq.eligible is True

    def test_max_duration_60(self, result):
        cdq = _find(result, ProductType.CDQ_PENSIONE)
        assert cdq.estimated_terms is not None
        assert cdq.estimated_terms.max_duration_months == 60


class TestNoCdqCapacity:
    """Dipendente privato, €1000, existing CdQ=€200 (max=200, available=0)."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.PRIVATO,
            net_monthly_income=Decimal("1000"),
            age=40,
            employer_size_employees=50,
            liabilities=[
                LiabilitySnapshot(
                    type=LiabilityType.CDQ,
                    monthly_installment=Decimal("200"),
                ),
            ],
        )
        return match_products(profile)

    def test_cdq_ineligible(self, result):
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.eligible is False

    def test_ineligibility_reason(self, result):
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.ineligibility_reason is not None
        assert "capacità" in cdq.ineligibility_reason.lower()


class TestPartitaIva:
    """Partita IVA, €3000, age 35, no liabilities."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.PARTITA_IVA,
            net_monthly_income=Decimal("3000"),
            age=35,
        )
        return match_products(profile)

    def test_no_cdq(self, result):
        cdq_s = _find(result, ProductType.CDQ_STIPENDIO)
        cdq_p = _find(result, ProductType.CDQ_PENSIONE)
        assert cdq_s.eligible is False
        assert cdq_p.eligible is False

    def test_no_delega(self, result):
        delega = _find(result, ProductType.DELEGA)
        assert delega.eligible is False

    def test_no_tfs(self, result):
        tfs = _find(result, ProductType.ANTICIPO_TFS)
        assert tfs.eligible is False

    def test_prestito_eligible(self, result):
        prestito = _find(result, ProductType.PRESTITO_PERSONALE)
        assert prestito.eligible is True

    def test_mutuo_acquisto_eligible(self, result):
        mutuo = _find(result, ProductType.MUTUO_ACQUISTO)
        assert mutuo.eligible is True


class TestZeroIncome:
    """Dipendente pubblico, €0 income, age 30."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.PUBBLICO,
            net_monthly_income=Decimal("0"),
            age=30,
        )
        return match_products(profile)

    def test_all_ineligible(self, result):
        eligible = [m for m in result.matches if m.eligible]
        assert len(eligible) == 0

    def test_dti_critical(self, result):
        assert result.profile_summary["dti_risk_level"] == "CRITICAL"


class TestMutuoSurrogaEligible:
    """Dipendente statale, €2500, existing MUTUO liability."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.STATALE,
            net_monthly_income=Decimal("2500"),
            age=40,
            liabilities=[
                LiabilitySnapshot(
                    type=LiabilityType.MUTUO,
                    monthly_installment=Decimal("500"),
                ),
            ],
        )
        return match_products(profile)

    def test_surroga_eligible(self, result):
        surroga = _find(result, ProductType.MUTUO_SURROGA)
        assert surroga.eligible is True

    def test_mutuo_acquisto_eligible(self, result):
        # DTI = 500/2500 = 0.20 < 0.35 and income >= 1000
        mutuo = _find(result, ProductType.MUTUO_ACQUISTO)
        assert mutuo.eligible is True


class TestCreditoAssicurativoCrossSell:
    """Dipendente pubblico, €2000, age 40 — assicurativo eligible via cross-sell."""

    @pytest.fixture()
    def result(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.PUBBLICO,
            net_monthly_income=Decimal("2000"),
            age=40,
        )
        return match_products(profile)

    def test_assicurativo_eligible(self, result):
        assic = _find(result, ProductType.CREDITO_ASSICURATIVO)
        assert assic.eligible is True

    def test_assicurativo_ranked_last(self, result):
        assic = _find(result, ProductType.CREDITO_ASSICURATIVO)
        assert assic.rank == 99


class TestDisoccupatoNoAssicurativo:
    """Disoccupato, €800 — assicurativo NOT eligible."""

    def test_assicurativo_ineligible(self):
        profile = UserProfile(
            employment_type=EmploymentType.DISOCCUPATO,
            net_monthly_income=Decimal("800"),
            age=35,
        )
        result = match_products(profile)
        assic = _find(result, ProductType.CREDITO_ASSICURATIVO)
        assert assic.eligible is False


class TestCdqCreditIssuesSuggestion:
    """Dipendente with credit issues — CdQ eligible + suggestion."""

    def test_credit_issues_suggestion(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.PUBBLICO,
            net_monthly_income=Decimal("2000"),
            age=40,
            has_credit_issues=True,
        )
        result = match_products(profile)
        cdq = _find(result, ProductType.CDQ_STIPENDIO)
        assert cdq.eligible is True

        credit_sug = [s for s in result.suggestions if s.suggestion_type == "cdq_credit_issues"]
        assert len(credit_sug) == 1


class TestPubblicoAdvantageSuggestion:
    """Dipendente statale — pubblico advantage suggestion."""

    def test_pubblico_suggestion(self):
        profile = UserProfile(
            employment_type=EmploymentType.DIPENDENTE,
            employer_category=EmployerCategory.STATALE,
            net_monthly_income=Decimal("2000"),
            age=40,
        )
        result = match_products(profile)
        pub_sug = [s for s in result.suggestions if s.suggestion_type == "pubblico_advantage"]
        assert len(pub_sug) == 1
        assert pub_sug[0].priority == 2
