"""FSM state definitions and transition map.

The conversation follows a strict state machine. The LLM generates natural
Italian responses but the FSM controls which transitions are valid.
"""

from __future__ import annotations

from src.models.enums import ConversationState

# Transition map: {current_state: {trigger_name: next_state}}
# Triggers come from the LLM's JSON action block or from system events.
TRANSITIONS: dict[ConversationState, dict[str, ConversationState]] = {
    ConversationState.WELCOME: {
        "proceed": ConversationState.CONSENT,
    },
    ConversationState.CONSENT: {
        "accepted": ConversationState.NEEDS_ASSESSMENT,
        "declined": ConversationState.COMPLETED,
    },
    ConversationState.NEEDS_ASSESSMENT: {
        "proceed": ConversationState.EMPLOYMENT_TYPE,
    },
    ConversationState.EMPLOYMENT_TYPE: {
        "dipendente": ConversationState.EMPLOYER_CLASS,
        "partita_iva": ConversationState.PIVA_COLLECTION,
        "pensionato": ConversationState.PENSION_CLASS,
        "disoccupato": ConversationState.HUMAN_ESCALATION,
        "mixed": ConversationState.HUMAN_ESCALATION,
    },
    ConversationState.PIVA_COLLECTION: {
        "complete": ConversationState.HOUSEHOLD,
    },
    ConversationState.EMPLOYER_CLASS: {
        "classified": ConversationState.TRACK_CHOICE,
    },
    ConversationState.PENSION_CLASS: {
        "classified": ConversationState.TRACK_CHOICE,
    },
    ConversationState.TRACK_CHOICE: {
        "fast_track": ConversationState.DOC_REQUEST,
        "manual": ConversationState.MANUAL_COLLECTION,
    },
    ConversationState.DOC_REQUEST: {
        "doc_received": ConversationState.DOC_PROCESSING,
    },
    ConversationState.DOC_PROCESSING: {
        "success": ConversationState.HOUSEHOLD,
        "retry": ConversationState.DOC_REQUEST,
    },
    ConversationState.MANUAL_COLLECTION: {
        "complete": ConversationState.HOUSEHOLD,
    },
    ConversationState.HOUSEHOLD: {
        "proceed": ConversationState.LIABILITIES,
    },
    ConversationState.LIABILITIES: {
        "proceed": ConversationState.CALCULATING,
        "no_liabilities": ConversationState.CALCULATING,
    },
    ConversationState.CALCULATING: {
        "done": ConversationState.RESULT,
    },
    ConversationState.RESULT: {
        "schedule": ConversationState.SCHEDULING,
        "done": ConversationState.COMPLETED,
    },
    ConversationState.SCHEDULING: {
        "booked": ConversationState.COMPLETED,
        "skip": ConversationState.COMPLETED,
    },
    ConversationState.COMPLETED: {},
    ConversationState.HUMAN_ESCALATION: {},
    ConversationState.ABANDONED: {},
}

# Every state can escalate to HUMAN_ESCALATION via /operatore command
UNIVERSAL_TRANSITIONS: dict[str, ConversationState] = {
    "escalate": ConversationState.HUMAN_ESCALATION,
}

# States where the conversation is considered "active" (not terminal)
ACTIVE_STATES: set[ConversationState] = {
    s for s in ConversationState
    if s not in {ConversationState.COMPLETED, ConversationState.HUMAN_ESCALATION, ConversationState.ABANDONED}
}
