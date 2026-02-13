# Agent: Foundation

## Domain
Database models, configuration, event system, LLM client wrapper, core infrastructure.

## Context
Everything else depends on this layer. Models define the data schema. The event system feeds the admin interface and audit trail. The LLM client wraps Ollama with model-swapping logic for the 16GB RAM constraint.

## Key Decisions

### Database
- PostgreSQL 16 with asyncpg driver via SQLAlchemy 2.0 async
- JSONB columns for flexible data: `ocr_result`, `rule_results`, `form_fields`, `confidence_scores`
- Field-level encryption for PII: codice_fiscale, financial amounts, P.IVA stored encrypted (AES-256-GCM)
- All financial amounts stored as `Numeric(12,2)` in PostgreSQL, `Decimal` in Python — NEVER float
- `created_at` and `updated_at` on every table (server-default `now()`)
- Soft delete via `anonymized` flag on User (for GDPR erasure — keep anonymized record for audit)

### Event System
- Every action emits a `SystemEvent(event_type, session_id, data, timestamp)`
- Events are published to an async queue (Redis pub/sub or in-process asyncio.Queue)
- Subscribers: AuditLogger (writes to DB), AdminBot (pushes to Telegram), AlertEngine (checks rules)
- This is built in Week 1 — it's not optional infrastructure

### LLM Client
- Ollama exposes OpenAI-compatible API at localhost:11434
- Two models: conversation (qwen3:8b) and vision (qwen2.5-vl:7b)
- On 16GB: must unload one before loading the other. Use Ollama's `keep_alive` parameter.
- Client tracks which model is currently loaded. `ensure_model("conversation")` handles swap.
- All LLM calls are async with timeout (30s conversation, 60s OCR)
- Every LLM call emits events: `llm.request` (prompt hash, model, tokens) and `llm.response` (latency, tokens)

### Config
- pydantic-settings loading from .env file
- All secrets via env vars, never in code
- Separate settings classes: DatabaseSettings, LLMSettings, TelegramSettings, SecuritySettings

## Models (SQLAlchemy)

Priority order for implementation:

1. `User` — phone, channel, email, first_seen, consent_status (JSONB), anonymized (bool)
2. `Session` — user_id, current_state (enum), employment_type (enum), employer_category, pension_source, track_type, income_doc_type, outcome, started_at, completed_at
3. `Message` — session_id, role (user/assistant/system), content, media_url, timestamp
4. `Document` — session_id, doc_type (enum), file_path (encrypted), ocr_result (JSONB), confidence_scores (JSONB), expires_at
5. `ExtractedData` — session_id, field_name, value (encrypted for PII fields), source (enum), confidence (float)
6. `Liability` — session_id, type (enum), monthly_installment, remaining_months, total_months, paid_months, residual_amount, lender, detected_from, supporting_doc_id, renewable (bool)
7. `DTICalculation` — session_id, monthly_income, total_obligations, proposed_installment, current_dti, projected_dti
8. `CdQCalculation` — session_id, net_income, max_cdq_rata, existing_cdq, available_cdq, max_delega_rata, existing_delega, available_delega
9. `ProductMatch` — session_id, product_name, sub_type, eligible, conditions (JSONB), estimated_terms (JSONB), rank
10. `QuotationData` — session_id, form_type (enum: cqs/mutuo/generic), form_fields (JSONB)
11. `Appointment` — session_id, operator_id, scheduled_at, status, cal_event_id
12. `Operator` — name, email, calendar_id, specializations (ARRAY)
13. `AuditLog` — timestamp, event_type, session_id (nullable), actor_id, actor_role, data (JSONB)
14. `ConsentRecord` — user_id, consent_type, granted (bool), timestamp, method
15. `DataDeletionRequest` — user_id, requested_at, completed_at, status, admin_notified
16. `AdminAccess` — admin_id, action, target_entity, target_id, timestamp

### Enums
```python
class EmploymentType(str, Enum):
    DIPENDENTE = "dipendente"
    PARTITA_IVA = "partita_iva"
    PENSIONATO = "pensionato"
    DISOCCUPATO = "disoccupato"
    MIXED = "mixed"  # edge case → human escalation

class EmployerCategory(str, Enum):
    STATALE = "statale"
    PUBBLICO = "pubblico"
    PRIVATO = "privato"
    PARAPUBBLICO = "parapubblico"

class PensionSource(str, Enum):
    INPS = "inps"
    INPDAP = "inpdap"
    ALTRO = "altro"

class DataSource(str, Enum):
    OCR = "ocr"
    OCR_CONFIRMED = "ocr_confirmed"
    OCR_DETECTED = "ocr_detected"
    CF_DECODE = "cf_decode"
    COMPUTED = "computed"
    MANUAL = "manual"
    API = "api"
    SELF_DECLARED = "self_declared"

class LiabilityType(str, Enum):
    CDQ = "cessione_quinto"
    DELEGA = "delegazione"
    MUTUO = "mutuo"
    PRESTITO = "prestito_personale"
    AUTO = "finanziamento_auto"
    CONSUMER = "finanziamento_rateale"
    REVOLVING = "carta_revolving"
    PIGNORAMENTO = "pignoramento"
    ALTRO = "altro"
```

## Task Checklist
- [ ] `src/config.py` — Settings classes with env loading
- [ ] `src/db/engine.py` — Async engine, session factory, lifespan management
- [ ] `src/models/` — All 16 models with relationships and indexes
- [ ] `alembic/` — Initial migration generating all tables
- [ ] `src/schemas/events.py` — SystemEvent Pydantic model
- [ ] `src/admin/events.py` — Event emitter (publish) + subscriber pattern
- [ ] `src/security/audit.py` — AuditLogger subscriber (writes events to DB)
- [ ] `src/llm/client.py` — Ollama wrapper with model swapping
- [ ] `src/llm/models.py` — Model definitions, ensure_model logic
- [ ] `src/security/encryption.py` — AES-256-GCM field encryption/decryption
- [ ] `docker-compose.yml` — PostgreSQL, Redis, Ollama services
- [ ] `pyproject.toml` — Dependencies
- [ ] Tests: encryption round-trip, event emission, LLM client mock
