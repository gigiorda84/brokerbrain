"""Tests for the conversation engine.

Covers: parse_llm_response, _build_context_section, _persist_extracted_data,
_persist_liability, _build_user_profile, _handle_doc_processing, SESSION_FIELD_MAP.

Uses mocks for DB, LLM, and event system.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation.engine import (
    PROGRAMMATIC_STATES,
    SESSION_FIELD_MAP,
    STATE_PROMPTS,
    _build_context_section,
    _build_user_profile,
    _get_extracted_value,
    _persist_extracted_data,
    _persist_liability,
    parse_llm_response,
)
from src.models.enums import (
    ConversationState,
    DataSource,
    EmploymentType,
    LiabilityType,
)


# ── parse_llm_response ──────────────────────────────────────────────


class TestParseLlmResponse:
    """Test the LLM response parser."""

    def test_valid_response(self):
        raw = 'Perfetto, procediamo!\n---\n{"action": "transition", "trigger": "proceed", "data": {}}'
        text, action = parse_llm_response(raw)
        assert text == "Perfetto, procediamo!"
        assert action == {"action": "transition", "trigger": "proceed", "data": {}}

    def test_no_separator(self):
        raw = "Just some text without separator"
        text, action = parse_llm_response(raw)
        assert text == raw
        assert action is None

    def test_invalid_json(self):
        raw = "Testo italiano\n---\n{not valid json"
        text, action = parse_llm_response(raw)
        assert text == "Testo italiano"
        assert action is None

    def test_multiple_separators(self):
        """Split on the LAST --- to handle --- in text."""
        raw = 'Text with --- inside\nMore text\n---\n{"action": "clarify", "reason": "test"}'
        text, action = parse_llm_response(raw)
        assert "Text with --- inside" in text
        assert action == {"action": "clarify", "reason": "test"}

    def test_collect_action(self):
        raw = 'Registrato.\n---\n{"action": "collect", "data": {"net_salary": "1800.00"}}'
        text, action = parse_llm_response(raw)
        assert action["action"] == "collect"
        assert action["data"]["net_salary"] == "1800.00"


# ── STATE_PROMPTS coverage ──────────────────────────────────────────


class TestStatePromptsMap:
    """Verify STATE_PROMPTS covers all LLM-driven states."""

    def test_all_llm_states_covered(self):
        """Every non-programmatic, non-terminal state should have a prompt."""
        terminal = {ConversationState.COMPLETED, ConversationState.ABANDONED, ConversationState.HUMAN_ESCALATION}
        for state in ConversationState:
            if state in PROGRAMMATIC_STATES or state in terminal:
                continue
            if state == ConversationState.DOC_UPLOAD:
                continue  # DOC_UPLOAD not used in transitions
            assert state in STATE_PROMPTS, f"Missing prompt for state {state.value}"

    def test_programmatic_states_not_in_prompts(self):
        for state in PROGRAMMATIC_STATES:
            assert state not in STATE_PROMPTS


# ── SESSION_FIELD_MAP ────────────────────────────────────────────────


class TestSessionFieldMap:
    """Verify SESSION_FIELD_MAP keys correspond to Session model attributes."""

    def test_all_mapped_fields_exist_on_session(self):
        from src.models.session import Session
        for data_key, attr_name in SESSION_FIELD_MAP.items():
            assert hasattr(Session, attr_name), f"Session missing attribute '{attr_name}' for key '{data_key}'"


# ── _build_context_section ──────────────────────────────────────────


class TestBuildContextSection:
    """Test context section builder."""

    def _make_session(self, **kwargs):
        """Create a mock session with configurable fields."""
        session = MagicMock()
        session.employment_type = kwargs.get("employment_type")
        session.employer_category = kwargs.get("employer_category")
        session.pension_source = kwargs.get("pension_source")
        session.track_type = kwargs.get("track_type")
        session.extracted_data = kwargs.get("extracted_data", [])
        session.liabilities = kwargs.get("liabilities", [])
        session.product_matches = kwargs.get("product_matches", [])
        return session

    def test_empty_session_returns_empty(self):
        session = self._make_session()
        result = _build_context_section(session)
        assert result == ""

    def test_employment_type_included(self):
        session = self._make_session(employment_type="dipendente")
        result = _build_context_section(session)
        assert "employment_type: dipendente" in result

    def test_extracted_data_included(self):
        ed = MagicMock()
        ed.field_name = "net_salary"
        ed.value = "1800.00"
        ed.source = "self_declared"
        session = self._make_session(extracted_data=[ed])
        result = _build_context_section(session)
        assert "net_salary: 1800.00" in result

    def test_liabilities_included(self):
        lib = MagicMock()
        lib.type = "prestito_personale"
        lib.monthly_installment = Decimal("250")
        session = self._make_session(liabilities=[lib])
        result = _build_context_section(session)
        assert "prestito_personale" in result
        assert "250" in result

    def test_product_matches_included(self):
        pm = MagicMock()
        pm.product_name = "CdQ Stipendio"
        pm.eligible = True
        pm.rank = 1
        pm.estimated_terms = None
        session = self._make_session(product_matches=[pm])
        result = _build_context_section(session)
        assert "CdQ Stipendio" in result
        assert "Eligible" in result


# ── _persist_extracted_data ─────────────────────────────────────────


class TestPersistExtractedData:
    """Test data persistence from LLM actions."""

    @pytest.mark.asyncio
    async def test_skips_session_fields(self):
        db = AsyncMock()
        session = MagicMock()
        session.id = uuid.uuid4()

        with patch("src.conversation.engine.emit", new_callable=AsyncMock):
            await _persist_extracted_data(db, session, {
                "employment_type": "dipendente",  # should be skipped
                "net_salary": "1800.00",  # should be persisted
            })

        # Only net_salary should be added (employment_type is in SESSION_FIELD_MAP)
        assert db.add.call_count == 1
        added = db.add.call_args[0][0]
        assert added.field_name == "net_salary"
        # net_salary is an encrypted field — verify it's marked and decryptable
        assert added.value_encrypted is True
        assert added.value != "1800.00"  # should be ciphertext

    @pytest.mark.asyncio
    async def test_skips_liability_key(self):
        db = AsyncMock()
        session = MagicMock()
        session.id = uuid.uuid4()

        with patch("src.conversation.engine.emit", new_callable=AsyncMock):
            await _persist_extracted_data(db, session, {
                "liability": {"type": "mutuo", "monthly_installment": "500"},
            })

        assert db.add.call_count == 0


# ── _persist_liability ──────────────────────────────────────────────


class TestPersistLiability:
    """Test liability persistence."""

    @pytest.mark.asyncio
    async def test_normalizes_type(self):
        db = AsyncMock()
        session = MagicMock()
        session.id = uuid.uuid4()

        with patch("src.conversation.engine.emit", new_callable=AsyncMock):
            await _persist_liability(db, session, {
                "type": "prestito_personale",
                "monthly_installment": "250.00",
            })

        assert db.add.call_count == 1
        liability = db.add.call_args[0][0]
        assert liability.type == LiabilityType.PRESTITO.value
        assert liability.monthly_installment == Decimal("250.00")

    @pytest.mark.asyncio
    async def test_handles_unknown_type(self):
        db = AsyncMock()
        session = MagicMock()
        session.id = uuid.uuid4()

        with patch("src.conversation.engine.emit", new_callable=AsyncMock):
            await _persist_liability(db, session, {
                "type": "unknown_type",
                "monthly_installment": "100",
            })

        liability = db.add.call_args[0][0]
        assert liability.type == LiabilityType.ALTRO.value

    @pytest.mark.asyncio
    async def test_handles_invalid_amount(self):
        db = AsyncMock()
        session = MagicMock()
        session.id = uuid.uuid4()

        with patch("src.conversation.engine.emit", new_callable=AsyncMock):
            await _persist_liability(db, session, {
                "type": "mutuo",
                "monthly_installment": "not_a_number",
            })

        liability = db.add.call_args[0][0]
        assert liability.monthly_installment == Decimal("0")


# ── _build_user_profile ─────────────────────────────────────────────


class TestBuildUserProfile:
    """Test UserProfile construction from session data."""

    def _make_session(self, **kwargs):
        session = MagicMock()
        session.employment_type = kwargs.get("employment_type", "dipendente")
        session.employer_category = kwargs.get("employer_category")
        session.pension_source = kwargs.get("pension_source")

        # Build extracted data mocks (unencrypted for test convenience)
        eds = []
        for field, value in kwargs.get("extracted_fields", {}).items():
            ed = MagicMock()
            ed.field_name = field
            ed.value = value
            ed.value_encrypted = False
            eds.append(ed)
        session.extracted_data = eds
        session.liabilities = kwargs.get("liabilities", [])
        return session

    def test_basic_dipendente(self):
        session = self._make_session(
            employment_type="dipendente",
            employer_category="pubblico",
            extracted_fields={"net_salary": "2000.00", "age": "40"},
        )
        profile = _build_user_profile(session)
        assert profile.employment_type == EmploymentType.DIPENDENTE
        assert profile.net_monthly_income == Decimal("2000.00")
        assert profile.age == 40

    def test_pensionato(self):
        session = self._make_session(
            employment_type="pensionato",
            pension_source="inps",
            extracted_fields={"net_pension": "1500.00", "age": "68"},
        )
        profile = _build_user_profile(session)
        assert profile.employment_type == EmploymentType.PENSIONATO
        assert profile.net_monthly_income == Decimal("1500.00")

    def test_with_liabilities(self):
        lib = MagicMock()
        lib.type = LiabilityType.PRESTITO.value
        lib.monthly_installment = Decimal("300")
        lib.remaining_months = 24
        lib.total_months = 60
        lib.paid_months = 36
        lib.residual_amount = Decimal("6000")
        lib.renewable = None

        session = self._make_session(
            extracted_fields={"net_salary": "2000", "age": "45"},
            liabilities=[lib],
        )
        profile = _build_user_profile(session)
        assert len(profile.liabilities) == 1
        assert profile.liabilities[0].monthly_installment == Decimal("300")

    def test_missing_income_defaults_zero(self):
        session = self._make_session(extracted_fields={"age": "30"})
        profile = _build_user_profile(session)
        assert profile.net_monthly_income == Decimal("0")


# ── _get_extracted_value ────────────────────────────────────────────


class TestGetExtractedValue:
    def test_found(self):
        ed = MagicMock()
        ed.field_name = "net_salary"
        ed.value = "2000"
        ed.value_encrypted = False
        session = MagicMock()
        session.extracted_data = [ed]
        assert _get_extracted_value(session, "net_salary") == "2000"

    def test_not_found(self):
        session = MagicMock()
        session.extracted_data = []
        assert _get_extracted_value(session, "missing_field") is None
