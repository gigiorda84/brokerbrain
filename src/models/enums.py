"""Domain enums used across SQLAlchemy models and Pydantic schemas.

All enums use str mixin for JSON serialization and PostgreSQL native enum types.
"""

from __future__ import annotations

from enum import Enum


class EmploymentType(str, Enum):
    """How the user is employed — drives product eligibility."""

    DIPENDENTE = "dipendente"
    PARTITA_IVA = "partita_iva"
    PENSIONATO = "pensionato"
    DISOCCUPATO = "disoccupato"
    MIXED = "mixed"  # edge case → human escalation


class EmployerCategory(str, Enum):
    """Employer classification for CdQ eligibility rules."""

    STATALE = "statale"
    PUBBLICO = "pubblico"
    PRIVATO = "privato"
    PARAPUBBLICO = "parapubblico"


class PensionSource(str, Enum):
    """Pension fund source — affects CdQ pension eligibility."""

    INPS = "inps"
    INPDAP = "inpdap"
    ALTRO = "altro"


class ContractType(str, Enum):
    """Employment contract type — extracted from busta paga."""

    INDETERMINATO = "indeterminato"
    DETERMINATO = "determinato"
    APPRENDISTATO = "apprendistato"


class PensionType(str, Enum):
    """Type of pension — extracted from cedolino pensione."""

    VECCHIAIA = "vecchiaia"
    ANTICIPATA = "anticipata"
    INVALIDITA = "invalidita"
    SUPERSTITI = "superstiti"
    SOCIALE = "sociale"


class TaxRegime(str, Enum):
    """Tax regime — extracted from dichiarazione redditi."""

    FORFETTARIO = "forfettario"
    ORDINARIO = "ordinario"
    SEMPLIFICATO = "semplificato"


class DataSource(str, Enum):
    """Tracks where each data field came from — feeds dossier confidence."""

    OCR = "ocr"
    OCR_CONFIRMED = "ocr_confirmed"
    OCR_DETECTED = "ocr_detected"
    CF_DECODE = "cf_decode"
    COMPUTED = "computed"
    MANUAL = "manual"
    API = "api"
    SELF_DECLARED = "self_declared"


class LiabilityType(str, Enum):
    """Types of existing financial obligations."""

    CDQ = "cessione_quinto"
    DELEGA = "delegazione"
    MUTUO = "mutuo"
    PRESTITO = "prestito_personale"
    AUTO = "finanziamento_auto"
    CONSUMER = "finanziamento_rateale"
    REVOLVING = "carta_revolving"
    PIGNORAMENTO = "pignoramento"
    ALTRO = "altro"


class DocumentType(str, Enum):
    """Recognized document types for OCR pipeline."""

    BUSTA_PAGA = "busta_paga"
    CEDOLINO_PENSIONE = "cedolino_pensione"
    CUD = "cud"
    DICHIARAZIONE_REDDITI = "dichiarazione_redditi"
    CONTEGGIO_ESTINTIVO = "conteggio_estintivo"
    F24 = "f24"
    DOCUMENTO_IDENTITA = "documento_identita"
    ALTRO = "altro"


class ConversationState(str, Enum):
    """FSM states for the conversation engine."""

    WELCOME = "welcome"
    CONSENT = "consent"
    NEEDS_ASSESSMENT = "needs_assessment"
    EMPLOYMENT_TYPE = "employment_type"
    EMPLOYER_CLASS = "employer_class"
    PENSION_CLASS = "pension_class"
    PIVA_COLLECTION = "piva_collection"
    TRACK_CHOICE = "track_choice"
    DOC_REQUEST = "doc_request"
    DOC_UPLOAD = "doc_upload"
    DOC_PROCESSING = "doc_processing"
    MANUAL_COLLECTION = "manual_collection"
    HOUSEHOLD = "household"
    LIABILITIES = "liabilities"
    CALCULATING = "calculating"
    RESULT = "result"
    SCHEDULING = "scheduling"
    COMPLETED = "completed"
    HUMAN_ESCALATION = "human_escalation"
    ABANDONED = "abandoned"


class SessionOutcome(str, Enum):
    """Final outcome of a qualification session."""

    QUALIFIED = "qualified"
    NOT_ELIGIBLE = "not_eligible"
    ABANDONED = "abandoned"
    HUMAN_ESCALATION = "human_escalation"
    SCHEDULED = "scheduled"


class MessageRole(str, Enum):
    """Message author role in conversation history."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChannelType(str, Enum):
    """Messaging channel the user is interacting through."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class ConsentType(str, Enum):
    """Types of consent tracked for GDPR compliance."""

    PRIVACY_POLICY = "privacy_policy"
    DATA_PROCESSING = "data_processing"
    MARKETING = "marketing"
    THIRD_PARTY = "third_party"


class QuotationFormType(str, Enum):
    """Primo Network quotation form types."""

    CQS = "cqs"
    MUTUO = "mutuo"
    GENERIC = "generic"


class AppointmentStatus(str, Enum):
    """Appointment lifecycle states."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class DeletionRequestStatus(str, Enum):
    """GDPR data deletion request status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
