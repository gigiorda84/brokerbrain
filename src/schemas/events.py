"""SystemEvent schema — the core event type that flows through the entire system.

Every action emits a SystemEvent. Subscribers (AuditLogger, AdminBot, AlertEngine)
consume these events asynchronously.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """All event types emitted by the system."""

    # Session lifecycle
    SESSION_STARTED = "session.started"
    SESSION_STATE_CHANGED = "session.state_changed"
    SESSION_COMPLETED = "session.completed"
    SESSION_ABANDONED = "session.abandoned"
    SESSION_ESCALATED = "session.escalated"

    # Messages
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"

    # Documents & OCR
    DOCUMENT_RECEIVED = "document.received"
    DOCUMENT_CLASSIFIED = "document.classified"
    OCR_STARTED = "ocr.started"
    OCR_COMPLETED = "ocr.completed"
    OCR_FAILED = "ocr.failed"

    # Data extraction
    DATA_EXTRACTED = "data.extracted"
    DATA_CONFIRMED = "data.confirmed"
    DATA_CORRECTED = "data.corrected"

    # Calculations
    DTI_CALCULATED = "calculation.dti"
    CDQ_CALCULATED = "calculation.cdq"

    # Eligibility
    ELIGIBILITY_CHECKED = "eligibility.checked"
    PRODUCT_MATCHED = "eligibility.product_matched"

    # Dossier
    DOSSIER_GENERATED = "dossier.generated"

    # Scheduling
    LEAD_QUALIFIED = "lead.qualified"
    APPOINTMENT_REQUESTED = "appointment.requested"
    APPOINTMENT_BOOKED = "appointment.booked"
    APPOINTMENT_CANCELLED = "appointment.cancelled"

    # LLM
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_MODEL_SWAP = "llm.model_swap"
    LLM_ERROR = "llm.error"

    # Consent & GDPR
    CONSENT_GRANTED = "consent.granted"
    CONSENT_REVOKED = "consent.revoked"
    DELETION_REQUESTED = "gdpr.deletion_requested"
    DELETION_COMPLETED = "gdpr.deletion_completed"

    # Admin
    ADMIN_ACCESS = "admin.access"
    ADMIN_OVERRIDE = "admin.override"
    ADMIN_ALERT = "admin.alert"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"
    SYSTEM_HEALTH_CHECK = "system.health_check"
    SYSTEM_MAINTENANCE = "system.maintenance"


class SystemEvent(BaseModel):
    """Core event that flows through the entire BrokerBot system.

    Immutable once created. Consumed by:
    - AuditLogger → writes to audit_log table
    - AdminBot → pushes notifications to Telegram admin group
    - AlertEngine → checks rules and triggers alerts
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Context (optional — not every event has a session)
    session_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    actor_id: str | None = None
    actor_role: str | None = None

    # Flexible payload
    data: dict[str, Any] = Field(default_factory=dict)

    # Metadata
    source_module: str | None = Field(default=None, description="Module that emitted this event")

    model_config = {"frozen": True}
