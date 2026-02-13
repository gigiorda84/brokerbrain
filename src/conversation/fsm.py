"""Finite state machine for conversation flow control.

The FSM validates transitions and emits state-change events.
The LLM never decides transitions — only the FSM does.
"""

from __future__ import annotations

import logging
import uuid

from src.admin.events import emit
from src.conversation.states import TRANSITIONS, UNIVERSAL_TRANSITIONS
from src.models.enums import ConversationState
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


class FSM:
    """Manages conversation state transitions for a single session."""

    def __init__(
        self,
        session_id: uuid.UUID,
        initial_state: ConversationState = ConversationState.WELCOME,
    ) -> None:
        self.session_id = session_id
        self.current_state = initial_state

    def can_transition(self, trigger: str) -> bool:
        """Check if a trigger is valid from the current state."""
        # Check universal transitions (e.g., /operatore → escalate)
        if trigger in UNIVERSAL_TRANSITIONS:
            return True
        state_transitions = TRANSITIONS.get(self.current_state, {})
        return trigger in state_transitions

    def get_valid_triggers(self) -> list[str]:
        """Return all valid trigger names for the current state."""
        triggers = list(TRANSITIONS.get(self.current_state, {}).keys())
        triggers.extend(UNIVERSAL_TRANSITIONS.keys())
        return triggers

    async def transition(self, trigger: str) -> ConversationState:
        """Execute a state transition.

        Args:
            trigger: The trigger name from the LLM action block or system event.

        Returns:
            The new state after transition.

        Raises:
            ValueError: If the trigger is not valid from the current state.
        """
        old_state = self.current_state

        # Check universal transitions first
        if trigger in UNIVERSAL_TRANSITIONS:
            self.current_state = UNIVERSAL_TRANSITIONS[trigger]
        else:
            state_transitions = TRANSITIONS.get(self.current_state, {})
            if trigger not in state_transitions:
                msg = (
                    f"Invalid transition: {self.current_state.value} --{trigger}--> ??? "
                    f"(valid: {list(state_transitions.keys())})"
                )
                raise ValueError(msg)
            self.current_state = state_transitions[trigger]

        logger.info(
            "State transition: %s --%s--> %s (session=%s)",
            old_state.value,
            trigger,
            self.current_state.value,
            self.session_id,
        )

        await emit(SystemEvent(
            event_type=EventType.SESSION_STATE_CHANGED,
            session_id=self.session_id,
            data={
                "from_state": old_state.value,
                "to_state": self.current_state.value,
                "trigger": trigger,
            },
            source_module="conversation.fsm",
        ))

        return self.current_state

    @property
    def is_terminal(self) -> bool:
        """Check if the current state is a terminal state."""
        return len(TRANSITIONS.get(self.current_state, {})) == 0
