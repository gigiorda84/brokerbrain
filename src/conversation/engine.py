"""Conversation orchestrator — the brain of BrokerBot.

Receives messages from channel adapters, determines state, builds prompts,
calls LLM, parses responses, extracts data, and transitions the FSM.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.admin.events import emit
from src.calculators.cdq import calculate_cdq_capacity
from src.calculators.dti import calculate_dti
from src.calculators.income import normalize_income
from src.conversation.fsm import FSM
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
from src.db.engine import redis_client as _redis
from src.decoders.codice_fiscale import decode_cf
from src.eligibility.engine import match_products
from src.llm.client import llm_client
from src.models.calculation import CdQCalculation, DTICalculation
from src.models.enums import ConversationState, DataSource, LiabilityType, MessageRole, SessionOutcome
from src.models.extracted_data import ExtractedData
from src.models.liability import Liability
from src.models.message import Message
from src.models.product_match import ProductMatch
from src.models.session import Session as SessionModel
from src.models.user import User
from src.ocr.pipeline import process_document
from src.schemas.calculators import DtiResult
from src.schemas.eligibility import EligibilityResult, LiabilitySnapshot, UserProfile
from src.schemas.events import EventType, SystemEvent
from src.security.consent import CONSENT_FIELD_MAP, consent_manager
from src.security.encryption import field_encryptor

logger = logging.getLogger(__name__)

# Map states to their system prompts (DOC_PROCESSING and CALCULATING are programmatic)
STATE_PROMPTS: dict[ConversationState, str] = {
    ConversationState.WELCOME: WELCOME_PROMPT,
    ConversationState.CONSENT: CONSENT_PROMPT,
    ConversationState.NEEDS_ASSESSMENT: NEEDS_ASSESSMENT_PROMPT,
    ConversationState.EMPLOYMENT_TYPE: EMPLOYMENT_TYPE_PROMPT,
    ConversationState.EMPLOYER_CLASS: EMPLOYER_CLASS_PROMPT,
    ConversationState.PENSION_CLASS: PENSION_CLASS_PROMPT,
    ConversationState.TRACK_CHOICE: TRACK_CHOICE_PROMPT,
    ConversationState.DOC_REQUEST: DOC_REQUEST_PROMPT,
    ConversationState.MANUAL_COLLECTION: MANUAL_COLLECTION_PROMPT,
    ConversationState.HOUSEHOLD: HOUSEHOLD_PROMPT,
    ConversationState.LIABILITIES: LIABILITIES_PROMPT,
    ConversationState.RESULT: RESULT_PROMPT,
    ConversationState.SCHEDULING: SCHEDULING_PROMPT,
}

# States handled programmatically (no LLM call)
PROGRAMMATIC_STATES: set[ConversationState] = {
    ConversationState.CALCULATING,
    ConversationState.DOC_PROCESSING,
}

# Fallback prompt for states without a dedicated prompt yet
FALLBACK_PROMPT = """You are the ameconviene.it assistant. The conversation is in a state
that doesn't have a dedicated prompt yet. Politely tell the user (in Italian, formal "lei")
that this feature is coming soon and suggest they call 800.99.00.90 to speak with a consultant.
---
{"action": "clarify", "reason": "state_not_implemented"}"""

# Maps data keys from LLM actions to Session model attributes
SESSION_FIELD_MAP: dict[str, str] = {
    "employment_type": "employment_type",
    "employer_category": "employer_category",
    "pension_source": "pension_source",
    "track_type": "track_type",
}

# Liability type normalization from LLM output to enum values
_LIABILITY_TYPE_MAP: dict[str, str] = {
    "cessione_quinto": LiabilityType.CDQ.value,
    "cessione_del_quinto": LiabilityType.CDQ.value,
    "delegazione": LiabilityType.DELEGA.value,
    "mutuo": LiabilityType.MUTUO.value,
    "prestito_personale": LiabilityType.PRESTITO.value,
    "prestito": LiabilityType.PRESTITO.value,
    "finanziamento_auto": LiabilityType.AUTO.value,
    "auto": LiabilityType.AUTO.value,
    "finanziamento_rateale": LiabilityType.CONSUMER.value,
    "carta_revolving": LiabilityType.REVOLVING.value,
    "pignoramento": LiabilityType.PIGNORAMENTO.value,
    "altro": LiabilityType.ALTRO.value,
}


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


def _build_context_section(session: SessionModel) -> str:
    """Build a context block from session fields and related data.

    Appended to the system prompt so the LLM knows what has already
    been collected (employment type, income, liabilities, etc.).
    """
    parts: list[str] = ["\n## Session Context (read-only, do not reveal raw data to user)"]

    if session.employment_type:
        parts.append(f"- employment_type: {session.employment_type}")
    if session.employer_category:
        parts.append(f"- employer_category: {session.employer_category}")
    if session.pension_source:
        parts.append(f"- pension_source: {session.pension_source}")
    if session.track_type:
        parts.append(f"- track_type: {session.track_type}")

    # Include extracted data fields
    if session.extracted_data:
        parts.append("- Extracted data:")
        for ed in session.extracted_data:
            parts.append(f"  - {ed.field_name}: {ed.value} (source: {ed.source})")

    # Include liabilities
    if session.liabilities:
        parts.append(f"- Liabilities ({len(session.liabilities)}):")
        for lib in session.liabilities:
            parts.append(f"  - {lib.type}: €{lib.monthly_installment}/month")

    # Include eligibility results if available (for RESULT state)
    if session.product_matches:
        parts.append("- Product matches:")
        for pm in session.product_matches:
            status = "✅ Eligible" if pm.eligible else "❌ Not eligible"
            parts.append(f"  - {pm.product_name}: {status} (rank: {pm.rank})")
            if pm.estimated_terms:
                parts.append(f"    Terms: {json.dumps(pm.estimated_terms, default=str)}")

    if len(parts) == 1:
        return ""  # No context to add
    return "\n".join(parts)


async def _persist_extracted_data(
    db: AsyncSession,
    session: SessionModel,
    data: dict,
    source: str = DataSource.SELF_DECLARED.value,
) -> None:
    """Save key-value pairs from LLM actions as ExtractedData rows."""
    for field_name, value in data.items():
        if field_name in SESSION_FIELD_MAP or field_name == "liability":
            continue  # Session fields and liabilities handled separately
        raw_value = str(value)
        should_encrypt = field_encryptor.should_encrypt(field_name)
        ed = ExtractedData(
            session_id=session.id,
            field_name=field_name,
            value=field_encryptor.encrypt(raw_value) if should_encrypt else raw_value,
            value_encrypted=should_encrypt,
            source=source,
            confidence=1.0 if source == DataSource.SELF_DECLARED.value else 0.9,
        )
        db.add(ed)

    await emit(SystemEvent(
        event_type=EventType.DATA_EXTRACTED,
        session_id=session.id,
        data={"fields": list(data.keys()), "source": source},
        source_module="conversation.engine",
    ))


async def _persist_liability(
    db: AsyncSession,
    session: SessionModel,
    liability_data: dict,
) -> None:
    """Save a liability from the LLM's collect action."""
    raw_type = str(liability_data.get("type", "altro"))
    normalized_type = _LIABILITY_TYPE_MAP.get(raw_type, LiabilityType.ALTRO.value)

    monthly_str = liability_data.get("monthly_installment", "0")
    try:
        monthly = Decimal(str(monthly_str))
    except (InvalidOperation, ValueError):
        monthly = Decimal("0")

    remaining = liability_data.get("remaining_months")
    if remaining is not None:
        try:
            remaining = int(remaining)
        except (ValueError, TypeError):
            remaining = None

    liability = Liability(
        session_id=session.id,
        type=normalized_type,
        monthly_installment=monthly,
        remaining_months=remaining,
        detected_from=DataSource.SELF_DECLARED.value,
    )
    db.add(liability)

    await emit(SystemEvent(
        event_type=EventType.DATA_EXTRACTED,
        session_id=session.id,
        data={"liability_type": normalized_type, "monthly": str(monthly)},
        source_module="conversation.engine",
    ))


def _get_extracted_value(session: SessionModel, field_name: str) -> str | None:
    """Look up a field value from the session's extracted data, decrypting if needed."""
    for ed in session.extracted_data:
        if ed.field_name == field_name:
            if ed.value_encrypted and ed.value:
                return field_encryptor.decrypt(ed.value)
            return ed.value
    return None


def _build_user_profile(session: SessionModel) -> UserProfile:
    """Build a UserProfile from session fields + ExtractedData + Liabilities."""
    from src.models.enums import EmployerCategory, EmploymentType, PensionSource

    employment_type = EmploymentType(session.employment_type or "dipendente")

    employer_category = None
    if session.employer_category:
        employer_category = EmployerCategory(session.employer_category)

    pension_source = None
    if session.pension_source:
        pension_source = PensionSource(session.pension_source)

    # Determine net monthly income from extracted data
    net_income = Decimal("0")
    raw_income_field = {
        EmploymentType.DIPENDENTE: "net_salary",
        EmploymentType.PENSIONATO: "net_pension",
        EmploymentType.PARTITA_IVA: "annual_revenue",
        EmploymentType.DISOCCUPATO: "net_salary",
    }.get(employment_type, "net_salary")

    raw_value = _get_extracted_value(session, raw_income_field)
    if raw_value:
        try:
            raw_decimal = Decimal(raw_value)
            if employment_type == EmploymentType.PARTITA_IVA:
                ateco = _get_extracted_value(session, "ateco_code")
                income_result = normalize_income(
                    employment_type.value.upper(),
                    raw_decimal,
                    ateco_code=ateco,
                )
                net_income = income_result.monthly_net
            else:
                net_income = raw_decimal
        except (InvalidOperation, ValueError):
            logger.warning("Could not parse income value: %s", raw_value)

    # Age from extracted data (CF decode or manual)
    age = 0
    age_str = _get_extracted_value(session, "age")
    if age_str:
        with contextlib.suppress(ValueError, TypeError):
            age = int(age_str)

    # Ex-public employee flag
    ex_pub_str = _get_extracted_value(session, "ex_public_employee")
    ex_public = ex_pub_str == "true" if ex_pub_str else False

    # Build liability snapshots
    liabilities: list[LiabilitySnapshot] = []
    for lib in session.liabilities:
        liabilities.append(LiabilitySnapshot(
            type=LiabilityType(lib.type),
            monthly_installment=lib.monthly_installment or Decimal("0"),
            remaining_months=lib.remaining_months,
            total_months=lib.total_months,
            paid_months=lib.paid_months,
            residual_amount=lib.residual_amount,
            renewable=lib.renewable,
        ))

    return UserProfile(
        employment_type=employment_type,
        employer_category=employer_category,
        pension_source=pension_source,
        ex_public_employee=ex_public,
        net_monthly_income=net_income,
        age=age,
        liabilities=liabilities,
    )


# ── Redis message cache ──────────────────────────────────────────────
# Cache last N messages per session to avoid DB queries on every message.
# Key: "session:{session_id}:messages", TTL: 1 hour, max 10 entries.

_MSG_CACHE_LIMIT = 10
_MSG_CACHE_TTL = 3600  # 1 hour


def _msg_cache_key(session_id: object) -> str:
    return f"session:{session_id}:messages"


async def _get_cached_messages(redis: aioredis.Redis, session_id: object) -> list[dict[str, str]] | None:
    """Get cached LLM message history from Redis. Returns None on cache miss."""
    key = _msg_cache_key(session_id)
    raw = await redis.lrange(key, 0, -1)
    if not raw:
        return None
    return [json.loads(item) for item in raw]


async def _push_cached_message(redis: aioredis.Redis, session_id: object, role: str, content: str) -> None:
    """Append a message to the Redis cache and trim to limit."""
    key = _msg_cache_key(session_id)
    entry = json.dumps({"role": role, "content": content})
    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -_MSG_CACHE_LIMIT, -1)
    pipe.expire(key, _MSG_CACHE_TTL)
    await pipe.execute()


async def _seed_cache_from_db(
    redis: aioredis.Redis, db: AsyncSession, session_id: object
) -> list[dict[str, str]]:
    """Load messages from DB into Redis cache on first access. Returns LLM-formatted messages."""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(_MSG_CACHE_LIMIT)
    )
    recent_messages = list(reversed(result.scalars().all()))

    llm_messages: list[dict[str, str]] = []
    pipe = redis.pipeline()
    key = _msg_cache_key(session_id)
    pipe.delete(key)
    for msg in recent_messages:
        if msg.role == MessageRole.SYSTEM.value:
            continue
        role = "user" if msg.role == MessageRole.USER.value else "assistant"
        entry = {"role": role, "content": msg.content}
        llm_messages.append(entry)
        pipe.rpush(key, json.dumps(entry))
    pipe.expire(key, _MSG_CACHE_TTL)
    await pipe.execute()
    return llm_messages


def _format_euro(amount: Decimal) -> str:
    """Format a Decimal as Italian currency: €1.750,00"""
    abs_val = abs(amount)
    integer_part = int(abs_val)
    decimal_part = abs_val - integer_part
    cents = round(decimal_part * 100)
    int_str = f"{integer_part:,}".replace(",", ".")
    return f"\u20ac{int_str},{cents:02d}"


def _format_result_response(
    result: EligibilityResult,
    eligible_products: list[str],
    dti: DtiResult,
) -> str:
    """Build a deterministic Italian result message from eligibility data.

    Replaces the second LLM call in _handle_calculating — no latency,
    consistent formatting, and the user still gets a natural presentation.
    """
    parts: list[str] = []

    if eligible_products:
        parts.append("Ecco i risultati della sua verifica preliminare!")
        parts.append("")
        parts.append("**Prodotti disponibili:**")
        parts.append("")
        rank = 1
        for match in sorted(result.matches, key=lambda m: m.rank or 99):
            if not match.eligible:
                continue
            line = f"{rank}. **{match.product_name}**"
            if match.sub_type:
                line += f" ({match.sub_type})"
            if match.estimated_terms:
                terms_parts: list[str] = []
                if match.estimated_terms.max_installment:
                    terms_parts.append(
                        f"rata max {_format_euro(match.estimated_terms.max_installment)}/mese"
                    )
                if match.estimated_terms.max_duration_months:
                    terms_parts.append(f"fino a {match.estimated_terms.max_duration_months} mesi")
                if match.estimated_terms.estimated_amount_max:
                    terms_parts.append(
                        f"importo fino a {_format_euro(match.estimated_terms.estimated_amount_max)}"
                    )
                if terms_parts:
                    line += " — " + ", ".join(terms_parts)
            parts.append(line)
            rank += 1
    else:
        parts.append("Purtroppo, in base ai dati forniti, al momento non risultano prodotti disponibili.")

    # Ineligible products brief mention
    ineligible = [m for m in result.matches if not m.eligible and m.ineligibility_reason]
    if ineligible:
        parts.append("")
        for m in ineligible:
            parts.append(f"- {m.product_name}: {m.ineligibility_reason}")

    # Smart suggestions
    if result.suggestions:
        parts.append("")
        for s in result.suggestions:
            parts.append(f"\U0001f4a1 {s.description}")

    # Disclaimer
    parts.append("")
    parts.append(
        "\u26a0\ufe0f Questa \u00e8 una verifica preliminare e non costituisce un'offerta vincolante. "
        "La valutazione definitiva sar\u00e0 effettuata da un consulente di Primo Network Srl."
    )

    # Next step
    parts.append("")
    parts.append(
        "Desidera fissare un appuntamento con un nostro consulente per approfondire? "
        "Oppure le bastano queste informazioni per ora?"
    )

    return "\n".join(parts)


def _extract_scheduling_preferences(session: SessionModel) -> dict[str, str]:
    """Pull scheduling preferences from session extracted data."""
    prefs: dict[str, str] = {}
    for key in ("preferred_time", "contact_method"):
        value = _get_extracted_value(session, key)
        if value:
            prefs[key] = value
    return prefs


def _determine_outcome(session: SessionModel) -> tuple[str, str | None]:
    """Determine session outcome from state and eligibility results."""
    if session.current_state == ConversationState.HUMAN_ESCALATION.value:
        return SessionOutcome.HUMAN_ESCALATION.value, None

    # Check if any products were eligible
    eligible = [pm for pm in session.product_matches if pm.eligible]
    if not eligible:
        return SessionOutcome.NOT_ELIGIBLE.value, "Nessun prodotto idoneo"

    return SessionOutcome.QUALIFIED.value, None


class ConversationEngine:
    """Orchestrates the conversation flow for all sessions."""

    async def get_or_create_user(
        self,
        db: AsyncSession,
        channel: str,
        channel_user_id: str,
        first_name: str | None = None,
    ) -> User:
        """Find or create a user by their channel-specific ID."""
        if channel == "whatsapp":
            result = await db.execute(
                select(User).where(User.whatsapp_id == channel_user_id)
            )
        else:
            result = await db.execute(
                select(User).where(User.telegram_id == channel_user_id)
            )
        user = result.scalar_one_or_none()

        if user is None:
            kwargs: dict[str, str | None] = {
                "first_name": first_name,
                "channel": channel,
            }
            if channel == "whatsapp":
                kwargs["whatsapp_id"] = channel_user_id
                kwargs["phone"] = channel_user_id
            else:
                kwargs["telegram_id"] = channel_user_id
            user = User(**kwargs)
            db.add(user)
            await db.flush()
            logger.info("Created new user: channel=%s, id=%s", channel, channel_user_id)

        return user

    async def get_or_create_session(
        self,
        db: AsyncSession,
        user: User,
        channel: str = "telegram",
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
            .options(
                selectinload(SessionModel.extracted_data),
                selectinload(SessionModel.liabilities),
                selectinload(SessionModel.product_matches),
            )
            .order_by(SessionModel.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

        if session is None:
            session = SessionModel(
                user_id=user.id,
                current_state=ConversationState.WELCOME.value,
                started_at=datetime.now(UTC),
            )
            db.add(session)
            await db.flush()
            # Reload session with all selectin relationships eagerly loaded
            await db.refresh(session, attribute_names=[
                "extracted_data", "liabilities", "product_matches",
            ])

            await emit(SystemEvent(
                event_type=EventType.SESSION_STARTED,
                session_id=session.id,
                user_id=user.id,
                data={"channel": channel},
                source_module="conversation.engine",
            ))
            logger.info("Created new session: id=%s user=%s", session.id, user.id)

        return session

    async def process_message(
        self,
        db: AsyncSession,
        channel_user_id: str,
        text: str,
        first_name: str | None = None,
        image_bytes: bytes | None = None,
        channel: str = "telegram",
    ) -> str:
        """Process an incoming message and return the bot's response.

        This is the main entry point called by channel adapters.

        Args:
            db: Database session.
            channel_user_id: Channel-specific user ID (Telegram ID or WhatsApp phone).
            text: The user's message text.
            first_name: User's first name from the channel.
            image_bytes: Optional document image bytes for OCR processing.
            channel: Channel identifier ("telegram" or "whatsapp").

        Returns:
            The bot's Italian response text (without the JSON action block).
        """
        # 1. Get or create user and session
        user = await self.get_or_create_user(db, channel, channel_user_id, first_name)
        session = await self.get_or_create_session(db, user, channel)

        # 2. Save incoming message
        msg_content = text or "[documento inviato]"
        user_msg = Message(
            session_id=session.id,
            role=MessageRole.USER.value,
            content=msg_content,
            state_at_send=session.current_state,
        )
        db.add(user_msg)
        await db.flush()

        # Push user message to Redis cache
        await _push_cached_message(_redis, session.id, "user", msg_content)

        await emit(SystemEvent(
            event_type=EventType.MESSAGE_RECEIVED,
            session_id=session.id,
            user_id=user.id,
            data={
                "text_length": len(text) if text else 0,
                "state": session.current_state,
                "has_image": image_bytes is not None,
            },
            source_module="conversation.engine",
        ))

        # 3. Build FSM
        current_state = ConversationState(session.current_state)
        fsm = FSM(session_id=session.id, initial_state=current_state)

        # 4. Handle image upload in DOC_REQUEST state → OCR pipeline
        if image_bytes and current_state == ConversationState.DOC_REQUEST:
            response_text = await self._handle_ocr_upload(
                db, session, user, fsm, image_bytes
            )
            return await self._save_and_return(db, session, user, response_text)

        # 5. Route programmatic states (CALCULATING, DOC_PROCESSING)
        if current_state in PROGRAMMATIC_STATES:
            response_text = await self._handle_programmatic_state(
                db, session, user, fsm, current_state, text
            )
            return await self._save_and_return(db, session, user, response_text)

        # 6. Get prompt for current state
        system_prompt = STATE_PROMPTS.get(current_state, FALLBACK_PROMPT)

        # Inject session context into prompt
        context_section = _build_context_section(session)
        if context_section:
            system_prompt = system_prompt + "\n" + context_section

        # 7. Load recent conversation history (Redis cache → DB fallback)
        llm_messages = await _get_cached_messages(_redis, session.id)
        if llm_messages is None:
            llm_messages = await _seed_cache_from_db(_redis, db, session.id)

        # 8. Call LLM (streaming — collects full response but gets first token faster)
        try:
            chunks: list[str] = []
            async for token in llm_client.chat_stream(
                system_prompt=system_prompt,
                messages=llm_messages,
            ):
                chunks.append(token)
            raw_response = "".join(chunks)
        except Exception:
            logger.exception("LLM call failed for session %s", session.id)
            raw_response = (
                "Mi scusi, sto riscontrando un problema tecnico. "
                "Può riprovare tra qualche istante oppure chiamare il numero verde 800.99.00.90.\n"
                "---\n"
                '{"action": "clarify", "reason": "llm_error"}'
            )

        # 9. Parse response
        response_text, action = parse_llm_response(raw_response)

        # 10. Handle action (transition or collect data)
        if action is not None:
            await self._handle_action(db, session, fsm, current_state, action)

        # 11. If we just transitioned to CALCULATING, handle it immediately
        new_state = ConversationState(session.current_state)
        if new_state == ConversationState.CALCULATING:
            calc_response = await self._handle_calculating(db, session, user, fsm)
            response_text = response_text + "\n\n" + calc_response

        # 12. If we just transitioned to a terminal state, finalize
        if new_state in (ConversationState.COMPLETED, ConversationState.HUMAN_ESCALATION):
            trigger = action.get("trigger") if action else None
            await self._handle_session_completed(db, session, user, trigger=trigger)

        return await self._save_and_return(db, session, user, response_text)

    async def _handle_action(
        self,
        db: AsyncSession,
        session: SessionModel,
        fsm: FSM,
        current_state: ConversationState,
        action: dict,
    ) -> None:
        """Process an LLM action (transition, collect, or clarify)."""
        action_type = action.get("action")
        trigger = action.get("trigger")
        data = action.get("data", {})

        if action_type == "transition" and trigger:
            if fsm.can_transition(trigger):
                await fsm.transition(trigger)
                session.current_state = fsm.current_state.value

                # Record consent when transitioning from CONSENT state
                if current_state == ConversationState.CONSENT:
                    user = await db.get(User, session.user_id)
                    if user is not None:
                        if trigger == "accepted":
                            for field_key, consent_type in CONSENT_FIELD_MAP.items():
                                granted = bool(data.get(field_key, True))
                                await consent_manager.record_consent(
                                    db, user.id, consent_type, granted=granted, method="chat",
                                )
                        elif trigger == "declined":
                            for consent_type in CONSENT_FIELD_MAP.values():
                                await consent_manager.record_consent(
                                    db, user.id, consent_type, granted=False, method="chat",
                                )

                # Store session-level fields
                for data_key, session_attr in SESSION_FIELD_MAP.items():
                    if data_key in data:
                        setattr(session, session_attr, data[data_key])

                # Persist extracted data fields
                if data:
                    await _persist_extracted_data(db, session, data)
            else:
                logger.warning(
                    "Invalid transition trigger '%s' from state %s",
                    trigger,
                    current_state.value,
                )

        elif action_type == "collect" and data:
            # Check for liability data
            if "liability" in data:
                await _persist_liability(db, session, data["liability"])

            # Store session-level fields from collect actions too
            for data_key, session_attr in SESSION_FIELD_MAP.items():
                if data_key in data:
                    setattr(session, session_attr, data[data_key])

            # Persist other extracted data
            await _persist_extracted_data(db, session, data)

            logger.info("Collected data: %s (session=%s)", list(data.keys()), session.id)

    async def _save_and_return(
        self,
        db: AsyncSession,
        session: SessionModel,
        user: User,
        response_text: str,
    ) -> str:
        """Save bot response message, update counts, emit event, and return."""
        bot_msg = Message(
            session_id=session.id,
            role=MessageRole.ASSISTANT.value,
            content=response_text,
            state_at_send=session.current_state,
        )
        db.add(bot_msg)

        # Push bot response to Redis message cache
        await _push_cached_message(_redis, session.id, "assistant", response_text)

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

    async def _handle_programmatic_state(
        self,
        db: AsyncSession,
        session: SessionModel,
        user: User,
        fsm: FSM,
        state: ConversationState,
        text: str,
    ) -> str:
        """Route programmatic states that don't use the LLM."""
        if state == ConversationState.CALCULATING:
            return await self._handle_calculating(db, session, user, fsm)
        if state == ConversationState.DOC_PROCESSING:
            return await self._handle_doc_processing(db, session, user, fsm, text)
        return (
            "Mi scusi, si è verificato un errore. "
            "Può chiamare il numero verde 800.99.00.90 per assistenza."
        )

    async def _handle_calculating(
        self,
        db: AsyncSession,
        session: SessionModel,
        user: User,
        fsm: FSM,
    ) -> str:
        """Run eligibility engine, persist results, transition to RESULT.

        1. Build UserProfile from session data
        2. Run match_products → persist ProductMatch rows
        3. Calculate DTI → persist DTICalculation
        4. Calculate CdQ capacity → persist CdQCalculation (if applicable)
        5. Transition CALCULATING → RESULT
        6. Return deterministic Italian template (no LLM call — saves 5-10s)
        """
        profile = _build_user_profile(session)
        eligibility_result = match_products(profile)

        # Persist product matches
        for match in eligibility_result.matches:
            pm = ProductMatch(
                session_id=session.id,
                product_name=match.product_name,
                sub_type=match.sub_type,
                eligible=match.eligible,
                conditions={
                    "conditions": [c.model_dump() for c in match.conditions],
                    "ineligibility_reason": match.ineligibility_reason,
                },
                estimated_terms=match.estimated_terms.model_dump() if match.estimated_terms else None,
                rank=match.rank,
            )
            db.add(pm)

        # Calculate and persist DTI
        obligations = [
            lib.monthly_installment or Decimal("0")
            for lib in session.liabilities
        ]
        dti_result = calculate_dti(profile.net_monthly_income, obligations)
        dti_calc = DTICalculation(
            session_id=session.id,
            monthly_income=dti_result.monthly_income,
            total_obligations=dti_result.total_obligations,
            proposed_installment=dti_result.proposed_installment,
            current_dti=dti_result.current_dti,
            projected_dti=dti_result.projected_dti,
        )
        db.add(dti_calc)

        await emit(SystemEvent(
            event_type=EventType.DTI_CALCULATED,
            session_id=session.id,
            user_id=user.id,
            data={
                "current_dti": str(dti_result.current_dti),
                "risk_level": dti_result.risk_level,
            },
            source_module="conversation.engine",
        ))

        # Calculate and persist CdQ capacity (for dipendente/pensionato)
        if profile.employment_type.value in ("dipendente", "pensionato"):
            existing_cdq = sum(
                (lib.monthly_installment or Decimal("0"))
                for lib in session.liabilities
                if lib.type == LiabilityType.CDQ.value
            )
            existing_delega = sum(
                (lib.monthly_installment or Decimal("0"))
                for lib in session.liabilities
                if lib.type == LiabilityType.DELEGA.value
            )
            cdq_result = calculate_cdq_capacity(
                profile.net_monthly_income,
                existing_cdq=existing_cdq,
                existing_delega=existing_delega,
            )
            cdq_calc = CdQCalculation(
                session_id=session.id,
                net_income=cdq_result.net_income,
                max_cdq_rata=cdq_result.max_cdq_rata,
                existing_cdq=cdq_result.existing_cdq,
                available_cdq=cdq_result.available_cdq,
                max_delega_rata=cdq_result.max_delega_rata,
                existing_delega=cdq_result.existing_delega,
                available_delega=cdq_result.available_delega,
            )
            db.add(cdq_calc)

            await emit(SystemEvent(
                event_type=EventType.CDQ_CALCULATED,
                session_id=session.id,
                user_id=user.id,
                data={
                    "available_cdq": str(cdq_result.available_cdq),
                    "available_delega": str(cdq_result.available_delega),
                },
                source_module="conversation.engine",
            ))

        # Store eligibility summary as ExtractedData for RESULT prompt context
        eligible_products = [m.product_name for m in eligibility_result.matches if m.eligible]
        summary_value = json.dumps({
            "eligible_products": eligible_products,
            "total_evaluated": len(eligibility_result.matches),
            "dti_risk": dti_result.risk_level,
            "suggestions": [s.model_dump() for s in eligibility_result.suggestions],
        }, default=str)
        ed = ExtractedData(
            session_id=session.id,
            field_name="eligibility_summary",
            value=summary_value,
            source=DataSource.COMPUTED.value,
            confidence=1.0,
        )
        db.add(ed)

        await emit(SystemEvent(
            event_type=EventType.ELIGIBILITY_CHECKED,
            session_id=session.id,
            user_id=user.id,
            data={
                "eligible_count": len(eligible_products),
                "total_count": len(eligibility_result.matches),
            },
            source_module="conversation.engine",
        ))

        # Transition CALCULATING → RESULT
        if fsm.can_transition("done"):
            await fsm.transition("done")
            session.current_state = fsm.current_state.value

        await db.flush()

        # Build deterministic Italian response from calculation results (no LLM call)
        return _format_result_response(eligibility_result, eligible_products, dti_result)

    async def _handle_session_completed(
        self,
        db: AsyncSession,
        session: SessionModel,
        user: User,
        trigger: str | None = None,
    ) -> None:
        """Finalize a completed session: outcome, dossier, events, cleanup."""
        from src.dossier.builder import build_dossier, load_session_for_dossier
        from src.dossier.quotation import persist_quotation_forms

        # 1. Set outcome
        outcome, reason = _determine_outcome(session)
        if trigger == "booked":
            outcome = SessionOutcome.SCHEDULED.value
            # Create appointment from scheduling preferences
            from src.scheduling.service import scheduling_service

            try:
                preferences = _extract_scheduling_preferences(session)
                await scheduling_service.create_appointment(db, session, user, preferences)
            except Exception:
                logger.exception("Failed to create appointment for session %s", session.id)
        session.outcome = outcome
        session.outcome_reason = reason
        session.completed_at = datetime.now(UTC)

        # 2. Build and persist dossier (only for qualified/scheduled)
        if outcome in (SessionOutcome.QUALIFIED.value, SessionOutcome.SCHEDULED.value):
            try:
                full_session = await load_session_for_dossier(db, str(session.id))
                if full_session:
                    dossier = build_dossier(full_session)
                    await persist_quotation_forms(db, dossier)
            except Exception:
                logger.exception("Failed to build dossier for session %s", session.id)

        # 3. Emit SESSION_COMPLETED event
        await emit(SystemEvent(
            event_type=EventType.SESSION_COMPLETED,
            session_id=session.id,
            user_id=user.id,
            data={
                "outcome": outcome,
                "outcome_reason": reason,
                "message_count": session.message_count,
            },
            source_module="conversation.engine",
        ))

        # 4. Clean up Redis message cache
        try:
            await _redis.delete(_msg_cache_key(session.id))
        except Exception:
            logger.warning("Failed to clean Redis cache for session %s", session.id)

        await db.flush()

    async def _handle_doc_processing(
        self,
        db: AsyncSession,
        session: SessionModel,
        user: User,
        fsm: FSM,
        text: str,
    ) -> str:
        """Handle document confirmation flow.

        User confirms or rejects extracted OCR data:
        - sì/confermo → transition("success") → HOUSEHOLD
        - no/correggi → transition("retry") → DOC_REQUEST
        """
        positive = text.lower().strip() in (
            "sì", "si", "yes", "ok", "confermo", "corretto", "va bene", "esatto",
        )
        negative = text.lower().strip() in (
            "no", "non", "sbagliato", "errato", "correggi", "rifai", "riprova",
        )

        if positive and fsm.can_transition("success"):
            # Upgrade OCR data source to confirmed
            for ed in session.extracted_data:
                if ed.source == DataSource.OCR.value:
                    ed.source = DataSource.OCR_CONFIRMED.value

            await fsm.transition("success")
            session.current_state = fsm.current_state.value

            await emit(SystemEvent(
                event_type=EventType.DATA_CONFIRMED,
                session_id=session.id,
                user_id=user.id,
                data={"confirmed": True},
                source_module="conversation.engine",
            ))

            return (
                "Perfetto, dati confermati! ✅\n\n"
                "Procediamo con qualche altra informazione sul suo nucleo familiare."
            )

        if negative and fsm.can_transition("retry"):
            await fsm.transition("retry")
            session.current_state = fsm.current_state.value

            return (
                "Nessun problema. Mi invii nuovamente il documento con una foto più chiara, "
                "oppure possiamo procedere con il percorso manuale."
            )

        # Unclear response
        return (
            "Mi scusi, non ho capito. I dati estratti dal documento sono corretti?\n\n"
            "Risponda con **sì** per confermare o **no** per riprovare."
        )

    async def _handle_ocr_upload(
        self,
        db: AsyncSession,
        session: SessionModel,
        user: User,
        fsm: FSM,
        image_bytes: bytes,
    ) -> str:
        """Process an uploaded document through the OCR pipeline.

        1. Determine expected document type from employment_type
        2. Call process_document()
        3. Save OCR fields as ExtractedData (source=OCR)
        4. Decode codice fiscale if found → save age/gender (source=cf_decode)
        5. Transition DOC_REQUEST → DOC_PROCESSING
        6. Present extracted data for confirmation
        """
        from src.models.enums import DocumentType

        # Determine expected doc type from employment
        expected_doc_type = None
        if session.employment_type == "dipendente":
            expected_doc_type = DocumentType.BUSTA_PAGA
        elif session.employment_type == "pensionato":
            expected_doc_type = DocumentType.CEDOLINO_PENSIONE

        ocr_result = await process_document(
            raw_image_bytes=image_bytes,
            session_id=session.id,
            user_id=user.id,
            expected_doc_type=expected_doc_type,
        )

        if ocr_result.error:
            return (
                f"⚠️ {ocr_result.error}\n\n"
                "Può riprovare con un'altra foto oppure passare al percorso manuale."
            )

        # Save OCR fields as ExtractedData
        extracted_fields: dict[str, str] = {}
        if ocr_result.extraction_result:
            result_dict = ocr_result.extraction_result.model_dump(exclude_none=True)
            skip_keys = {"confidence", "deductions"}
            for key, value in result_dict.items():
                if key in skip_keys:
                    continue
                str_value = str(value)
                extracted_fields[key] = str_value
                should_encrypt = field_encryptor.should_encrypt(key)
                ed = ExtractedData(
                    session_id=session.id,
                    field_name=key,
                    value=field_encryptor.encrypt(str_value) if should_encrypt else str_value,
                    value_encrypted=should_encrypt,
                    source=DataSource.OCR.value,
                    confidence=ocr_result.extraction_result.confidence.get(key, 0.0),
                )
                db.add(ed)

        # Decode codice fiscale if found
        cf_value = extracted_fields.get("codice_fiscale")
        if cf_value:
            try:
                cf_result = decode_cf(cf_value)
                for field, value in [
                    ("age", str(cf_result.age)),
                    ("gender", cf_result.gender),
                    ("birthdate", cf_result.birthdate.isoformat()),
                    ("birthplace", cf_result.birthplace_name),
                ]:
                    db.add(ExtractedData(
                        session_id=session.id,
                        field_name=field,
                        value=value,
                        source=DataSource.CF_DECODE.value,
                        confidence=1.0 if cf_result.valid else 0.5,
                    ))
            except ValueError:
                logger.warning("Failed to decode CF: %s", cf_value)

        # Transition DOC_REQUEST → DOC_PROCESSING
        if fsm.can_transition("doc_received"):
            await fsm.transition("doc_received")
            session.current_state = fsm.current_state.value

        # Build confirmation message
        parts = ["📄 Ho estratto i seguenti dati dal documento:\n"]
        display_map = {
            "employee_name": "Nome",
            "pensioner_name": "Nome",
            "codice_fiscale": "Codice Fiscale",
            "employer_name": "Datore di lavoro",
            "net_salary": "Stipendio netto",
            "net_pension": "Pensione netta",
            "gross_salary": "Stipendio lordo",
            "gross_pension": "Pensione lorda",
            "contract_type": "Tipo contratto",
            "hiring_date": "Data assunzione",
            "pension_type": "Tipo pensione",
            "pension_source": "Ente pensionistico",
        }
        for key, label in display_map.items():
            if key in extracted_fields:
                value = extracted_fields[key]
                if key in ("net_salary", "net_pension", "gross_salary", "gross_pension"):
                    value = f"€{value}"
                elif hasattr(value, "value"):
                    value = str(value.value).replace("_", " ").capitalize()
                parts.append(f"- {label}: {value}")

        if ocr_result.fields_needing_confirmation:
            parts.append(
                "\n⚠️ Alcuni campi hanno bassa confidenza: "
                + ", ".join(ocr_result.fields_needing_confirmation)
            )

        parts.append("\nI dati sono corretti? Risponda **sì** per confermare o **no** per riprovare.")

        return "\n".join(parts)


# Module-level singleton
conversation_engine = ConversationEngine()
