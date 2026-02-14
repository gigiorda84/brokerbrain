"""Eligibility engine — rule-based product matching for Primo Network products."""

from src.eligibility.engine import match_products
from src.eligibility.products import ProductType
from src.eligibility.suggestions import generate_suggestions
from src.schemas.eligibility import (
    EligibilityResult,
    LiabilitySnapshot,
    ProductMatchResult,
    SmartSuggestion,
    UserProfile,
)

__all__ = [
    "match_products",
    "generate_suggestions",
    "ProductType",
    "UserProfile",
    "LiabilitySnapshot",
    "ProductMatchResult",
    "EligibilityResult",
    "SmartSuggestion",
]
