"""Conversation orchestrator — the brain of BrokerBot.

Receives messages from channel adapters, determines state, builds prompts,
calls LLM, parses responses, extracts data, and transitions the FSM.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.events import emit
from src.conversation.fsm import FSM
from src.conversation.prompts.consent import CONSENT_PROMPT
from src.conversation.prompts.employment_type import EMPLOYMENT_TYPE_PROMPT
from src.conversation.prompts.needs_assessment import NEEDS_ASSESSMENT_PROMPT
from src.conversation.prompts.welcome import WELCOME_PROMPT
from src.llm.client import llm_client
from src.models.enums import ConversationState, MessageRole
from src.models.message import Message
from src.models.session import Session as SessionModel
from src.models.user import User
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)

# Map states to their system prompts
STATE_PROMPTS: dict[ConversationState, str] = {
    ConversationState.WELCOME: WELCOME_PROMPT,
    ConversationState.CONSENT: CONSENT_PROMPT,
    ConversationState.NEEDS_ASSESSMENT: NEEDS_ASSESSMENT_PROMPT,
    ConversationState.EMPLOYMENT_TYPE: EMPLOYMENT_TYPE_PROMPT,
}

# Fallback prompt for states without a dedicated prompt yet
FALLBACK_PROMPT = """You are the ameconviene.it assistant. The conversation is in a state
that doesn't have a dedicated prompt yet. Politely tell the user (in Italian, formal "lei")
that this feature is coming soon and suggest they call 800.99.00.90 to speak with a consultant.
---
{"action": "clarify", "reason": "state_not_implemented"}"""


def parse_llm_response(raw: str) -> tuple[str, dict | None]:
    """Split LLM response into user-facing text and JSON action block.

    The LLM is instructed to respond with:
        [Italian text]
        ---
        {"action": "...", ...}

    Returns:
        Tuple of (italian_text, action_dict_or_None).
    """
    if "---" not in raw:
        logger.warning("LLM response missing --- separator, treating as plain text")
        return raw.strip(), None

    # Split on the LAST occurrence of --- to handle --- in text
    parts = raw.rsplit("---", maxsplit=1)
    text = parts[0].strip()
    json_str = parts[1].strip()

    try:
        action = json.loads(json_str)
        return text, action
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM action JSON: %s", json_str[:200])
        return text, None


class ConversationEngine:
    """Orchestrates the conversation flow for all sessions."""

    async def get_or_create_user(
        self,
        db: AsyncSession,
        telegram_id: str,
        first_name: str | None = None,
    ) -> User:
        """Find or create a user by their Telegram ID."""
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                first_name=first_name,
                channel="telegram",
            )
            db.add(user)
            await db.flush()
            logger.info("Created new user: telegram_id=%s", telegram_id)

        return user

    async def get_or_create_session(
        self,
        db: AsyncSession,
        user: User,
    ) -> SessionModel:
        """Find the user's active session or create a new one."""
        # Look for an active (non-terminal) session
        result = await db.execute(
            select(SessionModel)
            .where(SessionModel.user_id == user.id)
            .where(SessionModel.current_state.notin_([
                ConversationState.COMPLETED.value,
                ConversationState.ABANDONED.value,
                ConversationState.HUMAN_ESCALATION.value,
            ]))
            .order_by(SessionModel.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

        if session is None:
            session = SessionModel(
                user_id=user.id,
                current_state=ConversationState.WELCOME.value,
                started_at=datetime.now(timezone.utc),
            )
            db.add(session)
            await db.flush()

            await emit(SystemEvent(
                event_type=EventType.SESSION_STARTED,
                session_id=session.id,
                user_id=user.id,
                data={"channel": "telegram"},
                source_module="conversation.engine",
            ))
            logger.info("Created new session: id=%s user=%s", session.id, user.id)

        return session

    async def process_message(
        self,
        db: AsyncSession,
        telegram_id: str,
        text: str,
        first_name: str | None = None,
    ) -> str:
        """Process an incoming message and return the bot's response.

        This is the main entry point called by the Telegram channel adapter.

        Args:
            db: Database session.
            telegram_id: Telegram user ID.
            text: The user's message text.
            first_name: User's Telegram first name.

        Returns:
            The bot's Italian response text (without the JSON action block).
        """
        # 1. Get or create user and session
        user = await self.get_or_create_user(db, telegram_id, first_name)
        session = await self.get_or_create_session(db, user)

        # 2. Save incoming message
        user_msg = Message(
            session_id=session.id,
            role=MessageRole.USER.value,
            content=text,
            state_at_send=session.current_state,
        )
        db.add(user_msg)

        await emit(SystemEvent(
            event_type=EventType.MESSAGE_RECEIVED,
            session_id=session.id,
            user_id=user.id,
            data={"text_length": len(text), "state": session.current_state},
            source_module="conversation.engine",
        ))

        # 3. Build FSM and get prompt for current state
        current_state = ConversationState(session.current_state)
        fsm = FSM(session_id=session.id, initial_state=current_state)
        system_prompt = STATE_PROMPTS.get(current_state, FALLBACK_PROMPT)

        # 4. Load recent conversation history for context
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        recent_messages = list(reversed(result.scalars().all()))

        # Build messages list for LLM (exclude current message, it's already added)
        llm_messages: list[dict[str, str]] = []
        for msg in recent_messages:
            if msg.role == MessageRole.SYSTEM.value:
                continue
            llm_messages.append({
                "role": "user" if msg.role == MessageRole.USER.value else "assistant",
                "content": msg.content,
            })

        # 5. Call LLM
        try:
            raw_response = await llm_client.chat(
                system_prompt=system_prompt,
                messages=llm_messages,
            )
        except Exception:
            logger.exception("LLM call failed for session %s", session.id)
            raw_response = (
                "Mi scusi, sto riscontrando un problema tecnico. "
                "Può riprovare tra qualche istante oppure chiamare il numero verde 800.99.00.90.\n"
                "---\n"
                '{"action": "clarify", "reason": "llm_error"}'
            )

        # 6. Parse response
        response_text, action = parse_llm_response(raw_response)

        # 7. Handle action (transition or collect data)
        if action is not None:
            action_type = action.get("action")
            trigger = action.get("trigger")
            data = action.get("data", {})

            if action_type == "transition" and trigger:
                if fsm.can_transition(trigger):
                    await fsm.transition(trigger)
                    session.current_state = fsm.current_state.value

                    # Store extracted data on session if relevant
                    if "employment_type" in data:
                        session.employment_type = data["employment_type"]
                    if "employer_category" in data:
                        session.employer_category = data["employer_category"]
                    if "pension_source" in data:
                        session.pension_source = data["pension_source"]
                else:
                    logger.warning(
                        "Invalid transition trigger '%s' from state %s",
                        trigger,
                        current_state.value,
                    )

            elif action_type == "collect" and data:
                logger.info("Collected data: %s (session=%s)", data, session.id)
                # Data collection without transition — store for later

        # 8. Save bot response
        bot_msg = Message(
            session_id=session.id,
            role=MessageRole.ASSISTANT.value,
            content=response_text,
            state_at_send=session.current_state,
        )
        db.add(bot_msg)

        # Update message count
        session.message_count = (session.message_count or 0) + 2

        await emit(SystemEvent(
            event_type=EventType.MESSAGE_SENT,
            session_id=session.id,
            user_id=user.id,
            data={"text_length": len(response_text), "state": session.current_state},
            source_module="conversation.engine",
        ))

        await db.flush()

        return response_text


# Module-level singleton
conversation_engine = ConversationEngine()
