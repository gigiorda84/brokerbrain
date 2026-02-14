"""Tests for FSM transitions across all conversation paths.

Covers: dipendente, pensionato, P.IVA tracks; manual vs fast track;
escalation; invalid triggers; terminal states.
"""

from __future__ import annotations

import uuid

import pytest

from src.conversation.fsm import FSM
from src.conversation.states import TRANSITIONS, UNIVERSAL_TRANSITIONS
from src.models.enums import ConversationState


@pytest.fixture()
def make_fsm():
    """Factory to create an FSM at a given state."""
    def _make(state: ConversationState = ConversationState.WELCOME) -> FSM:
        return FSM(session_id=uuid.uuid4(), initial_state=state)
    return _make


class TestDipendenteFullPath:
    """Dipendente → employer_class → track_choice → manual → household → liabilities → calculating → result → scheduling → completed."""

    @pytest.mark.asyncio
    async def test_dipendente_manual_path(self, make_fsm):
        fsm = make_fsm(ConversationState.WELCOME)

        await fsm.transition("proceed")
        assert fsm.current_state == ConversationState.CONSENT

        await fsm.transition("accepted")
        assert fsm.current_state == ConversationState.NEEDS_ASSESSMENT

        await fsm.transition("proceed")
        assert fsm.current_state == ConversationState.EMPLOYMENT_TYPE

        await fsm.transition("dipendente")
        assert fsm.current_state == ConversationState.EMPLOYER_CLASS

        await fsm.transition("classified")
        assert fsm.current_state == ConversationState.TRACK_CHOICE

        await fsm.transition("manual")
        assert fsm.current_state == ConversationState.MANUAL_COLLECTION

        await fsm.transition("complete")
        assert fsm.current_state == ConversationState.HOUSEHOLD

        await fsm.transition("proceed")
        assert fsm.current_state == ConversationState.LIABILITIES

        await fsm.transition("proceed")
        assert fsm.current_state == ConversationState.CALCULATING

        await fsm.transition("done")
        assert fsm.current_state == ConversationState.RESULT

        await fsm.transition("schedule")
        assert fsm.current_state == ConversationState.SCHEDULING

        await fsm.transition("booked")
        assert fsm.current_state == ConversationState.COMPLETED
        assert fsm.is_terminal

    @pytest.mark.asyncio
    async def test_dipendente_fast_track_path(self, make_fsm):
        fsm = make_fsm(ConversationState.TRACK_CHOICE)

        await fsm.transition("fast_track")
        assert fsm.current_state == ConversationState.DOC_REQUEST

        await fsm.transition("doc_received")
        assert fsm.current_state == ConversationState.DOC_PROCESSING

        await fsm.transition("success")
        assert fsm.current_state == ConversationState.HOUSEHOLD


class TestPensionatoPath:
    """Pensionato → pension_class → track_choice → ... → completed."""

    @pytest.mark.asyncio
    async def test_pensionato_path(self, make_fsm):
        fsm = make_fsm(ConversationState.EMPLOYMENT_TYPE)

        await fsm.transition("pensionato")
        assert fsm.current_state == ConversationState.PENSION_CLASS

        await fsm.transition("classified")
        assert fsm.current_state == ConversationState.TRACK_CHOICE


class TestPartitaIvaPath:
    """P.IVA skips employer/pension class → goes straight to HOUSEHOLD."""

    @pytest.mark.asyncio
    async def test_partita_iva_path(self, make_fsm):
        fsm = make_fsm(ConversationState.EMPLOYMENT_TYPE)

        await fsm.transition("partita_iva")
        assert fsm.current_state == ConversationState.HOUSEHOLD


class TestEscalationPaths:
    """Escalation from any active state via universal trigger."""

    @pytest.mark.asyncio
    async def test_escalate_from_employment_type(self, make_fsm):
        fsm = make_fsm(ConversationState.EMPLOYMENT_TYPE)

        assert fsm.can_transition("escalate")
        await fsm.transition("escalate")
        assert fsm.current_state == ConversationState.HUMAN_ESCALATION
        assert fsm.is_terminal

    @pytest.mark.asyncio
    async def test_escalate_from_household(self, make_fsm):
        fsm = make_fsm(ConversationState.HOUSEHOLD)
        await fsm.transition("escalate")
        assert fsm.current_state == ConversationState.HUMAN_ESCALATION

    @pytest.mark.asyncio
    async def test_disoccupato_escalates(self, make_fsm):
        fsm = make_fsm(ConversationState.EMPLOYMENT_TYPE)
        await fsm.transition("disoccupato")
        assert fsm.current_state == ConversationState.HUMAN_ESCALATION

    @pytest.mark.asyncio
    async def test_mixed_escalates(self, make_fsm):
        fsm = make_fsm(ConversationState.EMPLOYMENT_TYPE)
        await fsm.transition("mixed")
        assert fsm.current_state == ConversationState.HUMAN_ESCALATION


class TestInvalidTransitions:
    """Invalid trigger handling."""

    def test_invalid_trigger_not_allowed(self, make_fsm):
        fsm = make_fsm(ConversationState.WELCOME)
        assert not fsm.can_transition("dipendente")

    @pytest.mark.asyncio
    async def test_invalid_trigger_raises(self, make_fsm):
        fsm = make_fsm(ConversationState.WELCOME)
        with pytest.raises(ValueError, match="Invalid transition"):
            await fsm.transition("dipendente")

    def test_no_transitions_from_completed(self, make_fsm):
        fsm = make_fsm(ConversationState.COMPLETED)
        assert fsm.is_terminal
        assert not fsm.can_transition("proceed")


class TestDocProcessingRetry:
    """DOC_PROCESSING retry loop."""

    @pytest.mark.asyncio
    async def test_retry_returns_to_doc_request(self, make_fsm):
        fsm = make_fsm(ConversationState.DOC_PROCESSING)
        await fsm.transition("retry")
        assert fsm.current_state == ConversationState.DOC_REQUEST

    @pytest.mark.asyncio
    async def test_success_goes_to_household(self, make_fsm):
        fsm = make_fsm(ConversationState.DOC_PROCESSING)
        await fsm.transition("success")
        assert fsm.current_state == ConversationState.HOUSEHOLD


class TestResultPaths:
    """RESULT state branching."""

    @pytest.mark.asyncio
    async def test_result_schedule(self, make_fsm):
        fsm = make_fsm(ConversationState.RESULT)
        await fsm.transition("schedule")
        assert fsm.current_state == ConversationState.SCHEDULING

    @pytest.mark.asyncio
    async def test_result_done(self, make_fsm):
        fsm = make_fsm(ConversationState.RESULT)
        await fsm.transition("done")
        assert fsm.current_state == ConversationState.COMPLETED

    @pytest.mark.asyncio
    async def test_scheduling_skip(self, make_fsm):
        fsm = make_fsm(ConversationState.SCHEDULING)
        await fsm.transition("skip")
        assert fsm.current_state == ConversationState.COMPLETED


class TestNoLiabilities:
    """LIABILITIES no_liabilities trigger."""

    @pytest.mark.asyncio
    async def test_no_liabilities_goes_to_calculating(self, make_fsm):
        fsm = make_fsm(ConversationState.LIABILITIES)
        await fsm.transition("no_liabilities")
        assert fsm.current_state == ConversationState.CALCULATING


class TestConsentDeclined:
    """Consent declined → completed."""

    @pytest.mark.asyncio
    async def test_consent_declined(self, make_fsm):
        fsm = make_fsm(ConversationState.CONSENT)
        await fsm.transition("declined")
        assert fsm.current_state == ConversationState.COMPLETED
        assert fsm.is_terminal


class TestValidTriggers:
    """get_valid_triggers returns correct list."""

    def test_employment_type_triggers(self, make_fsm):
        fsm = make_fsm(ConversationState.EMPLOYMENT_TYPE)
        triggers = fsm.get_valid_triggers()
        assert "dipendente" in triggers
        assert "pensionato" in triggers
        assert "partita_iva" in triggers
        assert "disoccupato" in triggers
        assert "mixed" in triggers
        assert "escalate" in triggers  # universal

    def test_completed_only_escalate(self, make_fsm):
        fsm = make_fsm(ConversationState.COMPLETED)
        triggers = fsm.get_valid_triggers()
        assert triggers == ["escalate"]
