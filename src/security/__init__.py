"""Security & GDPR module — encryption, consent, erasure, audit."""

from src.security.consent import consent_manager
from src.security.erasure import erasure_processor

__all__ = ["consent_manager", "erasure_processor"]
