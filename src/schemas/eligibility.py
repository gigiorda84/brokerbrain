"""Pydantic schemas for the eligibility engine.

Input: UserProfile + LiabilitySnapshot (built by conversation handler).
Output: EligibilityResult with per-product matches, terms, and suggestions.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.models.enums import EmployerCategory, EmploymentType, LiabilityType, PensionSource

# ── Input schemas ──────────────────────────────────────────────────────────


class LiabilitySnapshot(BaseModel):
    """Lightweight liability representation for rule evaluation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: LiabilityType
    monthly_installment: Decimal
    remaining_months: int | None = None
    total_months: int | None = None
    paid_months: int | None = None
    residual_amount: Decimal | None = None
    renewable: bool | None = None


class UserProfile(BaseModel):
    """All data the eligibility engine needs to evaluate products."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    employment_type: EmploymentType
    employer_category: EmployerCategory | None = None
    pension_source: PensionSource | None = None
    ex_public_employee: bool = False
    net_monthly_income: Decimal
    age: int
    liabilities: list[LiabilitySnapshot] = []
    employer_size_employees: int | None = None
    employer_allows_delega: bool | None = None
    has_credit_issues: bool = False


# ── Output schemas ─────────────────────────────────────────────────────────


class RuleCondition(BaseModel):
    """A single evaluated condition within a product check."""

    name: str
    description: str  # Italian, user-facing
    met: bool
    is_hard: bool
    value: str | None = None


class EstimatedTerms(BaseModel):
    """Estimated product terms when a user is eligible."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    max_installment: Decimal | None = None
    max_duration_months: int | None = None
    estimated_amount_min: Decimal | None = None
    estimated_amount_max: Decimal | None = None
    notes: str | None = None


class ProductMatchResult(BaseModel):
    """Result of evaluating one product against a user profile."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    product_name: str
    sub_type: str | None = None
    eligible: bool
    conditions: list[RuleCondition]
    estimated_terms: EstimatedTerms | None = None
    rank: int | None = None
    ineligibility_reason: str | None = None


class SmartSuggestion(BaseModel):
    """A proactive suggestion based on the user's profile and matches."""

    suggestion_type: str
    title: str
    description: str  # Italian, user-facing
    priority: int
    related_products: list[str] = []


class EligibilityResult(BaseModel):
    """Full output of the eligibility engine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    matches: list[ProductMatchResult]
    suggestions: list[SmartSuggestion] = []
    profile_summary: dict[str, object] = {}
