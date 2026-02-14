"""Tests for all conversation prompts.

Verifies every prompt contains IDENTITY, TONE, RESPONSE_FORMAT,
and declares valid triggers consistent with the FSM transition map.
"""

from __future__ import annotations

import pytest

from src.conversation.prompts.base import DISCLAIMER, IDENTITY, RESPONSE_FORMAT, TONE
from src.conversation.prompts.consent import CONSENT_PROMPT
from src.conversation.prompts.doc_request import DOC_REQUEST_PROMPT
from src.conversation.prompts.employer_class import EMPLOYER_CLASS_PROMPT
from src.conversation.prompts.employment_type import EMPLOYMENT_TYPE_PROMPT
from src.conversation.prompts.household import HOUSEHOLD_PROMPT
from src.conversation.prompts.liabilities import LIABILITIES_PROMPT
from src.conversation.prompts.manual_collection import MANUAL_COLLECTION_PROMPT
from src.conversation.prompts.needs_assessment import NEEDS_ASSESSMENT_PROMPT
from src.conversation.prompts.pension_class import PENSION_CLASS_PROMPT
from src.conversation.prompts.result import RESULT_PROMPT
from src.conversation.prompts.scheduling import SCHEDULING_PROMPT
from src.conversation.prompts.track_choice import TRACK_CHOICE_PROMPT
from src.conversation.prompts.welcome import WELCOME_PROMPT
from src.conversation.states import TRANSITIONS
from src.models.enums import ConversationState

# All prompts with their state and expected triggers
PROMPT_CASES = [
    ("WELCOME", WELCOME_PROMPT, ConversationState.WELCOME),
    ("CONSENT", CONSENT_PROMPT, ConversationState.CONSENT),
    ("NEEDS_ASSESSMENT", NEEDS_ASSESSMENT_PROMPT, ConversationState.NEEDS_ASSESSMENT),
    ("EMPLOYMENT_TYPE", EMPLOYMENT_TYPE_PROMPT, ConversationState.EMPLOYMENT_TYPE),
    ("EMPLOYER_CLASS", EMPLOYER_CLASS_PROMPT, ConversationState.EMPLOYER_CLASS),
    ("PENSION_CLASS", PENSION_CLASS_PROMPT, ConversationState.PENSION_CLASS),
    ("TRACK_CHOICE", TRACK_CHOICE_PROMPT, ConversationState.TRACK_CHOICE),
    ("DOC_REQUEST", DOC_REQUEST_PROMPT, ConversationState.DOC_REQUEST),
    ("MANUAL_COLLECTION", MANUAL_COLLECTION_PROMPT, ConversationState.MANUAL_COLLECTION),
    ("HOUSEHOLD", HOUSEHOLD_PROMPT, ConversationState.HOUSEHOLD),
    ("LIABILITIES", LIABILITIES_PROMPT, ConversationState.LIABILITIES),
    ("RESULT", RESULT_PROMPT, ConversationState.RESULT),
    ("SCHEDULING", SCHEDULING_PROMPT, ConversationState.SCHEDULING),
]


@pytest.mark.parametrize(
    ("name", "prompt", "state"),
    PROMPT_CASES,
    ids=[c[0] for c in PROMPT_CASES],
)
class TestPromptStructure:
    """Verify structural requirements for all prompts."""

    def test_contains_identity(self, name, prompt, state):
        # IDENTITY content should be embedded (it's an f-string include)
        assert "ameconviene.it" in prompt
        assert "Primo Network" in prompt

    def test_contains_tone(self, name, prompt, state):
        assert "lei" in prompt.lower() or "Communication rules" in prompt

    def test_contains_response_format(self, name, prompt, state):
        assert "---" in prompt
        assert "action" in prompt

    def test_contains_valid_triggers(self, name, prompt, state):
        """The prompt should mention the triggers defined in the FSM transition map."""
        triggers = TRANSITIONS.get(state, {})
        for trigger_name in triggers:
            assert trigger_name in prompt, (
                f"Prompt {name} missing trigger '{trigger_name}' "
                f"(valid triggers for {state.value}: {list(triggers.keys())})"
            )


class TestResultPromptHasDisclaimer:
    """RESULT prompt must include the disclaimer."""

    def test_disclaimer_content(self):
        assert "verifica preliminare" in RESULT_PROMPT
        assert "offerta vincolante" in RESULT_PROMPT


class TestPromptExamples:
    """Verify prompts contain example responses with proper format."""

    @pytest.mark.parametrize(
        ("name", "prompt", "state"),
        PROMPT_CASES,
        ids=[c[0] for c in PROMPT_CASES],
    )
    def test_has_example(self, name, prompt, state):
        assert "Example" in prompt or "example" in prompt.lower()
