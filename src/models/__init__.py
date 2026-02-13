"""SQLAlchemy ORM models for BrokerBot.

Import all models here so Alembic and Base.metadata.create_all() discover them.
"""

from __future__ import annotations

from src.models.admin_access import AdminAccess
from src.models.appointment import Appointment
from src.models.audit import AuditLog
from src.models.base import Base
from src.models.calculation import CdQCalculation, DTICalculation
from src.models.consent import ConsentRecord
from src.models.deletion import DataDeletionRequest
from src.models.document import Document
from src.models.enums import (
    AppointmentStatus,
    ChannelType,
    ConsentType,
    ConversationState,
    DataSource,
    DeletionRequestStatus,
    DocumentType,
    EmployerCategory,
    EmploymentType,
    LiabilityType,
    MessageRole,
    PensionSource,
    QuotationFormType,
    SessionOutcome,
)
from src.models.extracted_data import ExtractedData
from src.models.liability import Liability
from src.models.message import Message
from src.models.operator import Operator
from src.models.product_match import ProductMatch
from src.models.quotation import QuotationData
from src.models.session import Session
from src.models.user import User

__all__ = [
    # Base
    "Base",
    # Models
    "User",
    "Session",
    "Message",
    "Document",
    "ExtractedData",
    "Liability",
    "DTICalculation",
    "CdQCalculation",
    "ProductMatch",
    "QuotationData",
    "Appointment",
    "Operator",
    "AuditLog",
    "ConsentRecord",
    "DataDeletionRequest",
    "AdminAccess",
    # Enums
    "EmploymentType",
    "EmployerCategory",
    "PensionSource",
    "DataSource",
    "LiabilityType",
    "DocumentType",
    "ConversationState",
    "SessionOutcome",
    "MessageRole",
    "ChannelType",
    "ConsentType",
    "QuotationFormType",
    "AppointmentStatus",
    "DeletionRequestStatus",
]
