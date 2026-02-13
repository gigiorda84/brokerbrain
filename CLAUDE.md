# CLAUDE.md — BrokerBot (ameconviene.it)

## Project Overview

BrokerBot is an AI-powered lead qualification chatbot for **ameconviene.it** (consumer brand of **Primo Network Srl**, Italian credit brokerage, OAM M94, Turin). It qualifies consumers for 9 financial products (cessione del quinto, prestiti, mutui, TFS, insurance) via WhatsApp/Telegram, using local LLMs for conversation and document OCR.

**Owner:** Giuseppe Giordano
**Legal entity:** Primo Network Srl (P.IVA 08154920014)
**Full PRD:** `docs/PRD_v1.5.md` — read this for complete business logic, product rules, and regulatory requirements.

## Architecture

```
User (WhatsApp/Telegram)
  → FastAPI webhook
    → Conversation Engine (FSM + Qwen3 8B via Ollama)
      → OCR Pipeline (Qwen2.5-VL 7B via Ollama) — when documents received
      → CF Decoder (pure Python) — extract age/gender from codice fiscale
      → Liabilities Collector — existing debts, CdQ detection
      → Calculators (DTI, CdQ rata/capacity/renewal) — pure Python
      → Eligibility Engine — rule-based product matching
      → Dossier Builder — pre-fill Primo Network quotation forms
    → Admin Interface (Telegram bot + FastAPI/HTMX dashboard)
  → Scheduling (Cal.com/Calendly API)
  → PostgreSQL + Redis
```

## Tech Stack

- **Python 3.12+**, **FastAPI**, async throughout
- **Ollama** for LLM serving (Qwen3 8B conversation, Qwen2.5-VL 7B OCR)
- **PostgreSQL 16** with JSONB, **Redis** for session state and queues
- **python-telegram-bot** for both user bot and admin bot
- **Docker Compose** for local development and deployment
- **Jinja2 + HTMX** for admin web dashboard (no frontend build step)
- **Pydantic v2** for all data validation
- **SQLAlchemy 2.0** async ORM
- **Alembic** for migrations

## Project Structure

```
brokerbot/
├── CLAUDE.md                    # This file
├── docs/
│   └── PRD_v1.5.md             # Full product requirements
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan, webhook endpoints
│   ├── config.py                # Settings via pydantic-settings (env vars)
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── session.py
│   │   ├── message.py
│   │   ├── document.py
│   │   ├── extracted_data.py
│   │   ├── liability.py
│   │   ├── calculation.py
│   │   ├── product_match.py
│   │   ├── appointment.py
│   │   ├── audit.py
│   │   └── consent.py
│   ├── schemas/                 # Pydantic schemas (request/response/internal)
│   │   ├── __init__.py
│   │   ├── ocr.py               # OCR extraction schemas per document type
│   │   ├── eligibility.py       # Product matching input/output
│   │   ├── quotation.py         # Pre-filled form data for Primo Network
│   │   ├── dossier.py           # Lead dossier structure
│   │   └── events.py            # System event schemas
│   ├── conversation/            # Conversation engine
│   │   ├── __init__.py
│   │   ├── engine.py            # Main orchestrator: receive message → process → respond
│   │   ├── states.py            # State enum + transition rules
│   │   ├── fsm.py               # Finite state machine implementation
│   │   ├── prompts/             # LLM system prompts per state
│   │   │   ├── welcome.py
│   │   │   ├── consent.py
│   │   │   ├── needs_assessment.py
│   │   │   ├── employment_type.py
│   │   │   ├── employer_class.py
│   │   │   ├── pension_class.py
│   │   │   ├── track_choice.py
│   │   │   ├── doc_request.py
│   │   │   ├── manual_collection.py
│   │   │   ├── household.py
│   │   │   ├── liabilities.py
│   │   │   ├── result.py
│   │   │   ├── scheduling.py
│   │   │   └── base.py          # Shared prompt components (identity, tone, disclaimers)
│   │   └── handlers/            # Per-state message handlers
│   │       ├── __init__.py
│   │       └── ... (one per state or group)
│   ├── ocr/                     # Document processing pipeline
│   │   ├── __init__.py
│   │   ├── pipeline.py          # Main pipeline: receive doc → classify → extract → validate
│   │   ├── preprocessor.py      # Image preprocessing (resize, orient, contrast)
│   │   ├── classifier.py        # Document type classification
│   │   ├── extractors/          # Type-specific extraction prompts
│   │   │   ├── busta_paga.py
│   │   │   ├── cedolino_pensione.py
│   │   │   ├── dichiarazione_redditi.py
│   │   │   ├── conteggio_estintivo.py
│   │   │   └── f24.py
│   │   └── validator.py         # Post-extraction validation (ranges, checksums, dates)
│   ├── decoders/                # Deterministic data decoders
│   │   ├── __init__.py
│   │   ├── codice_fiscale.py    # CF → birthdate, age, gender, birthplace
│   │   └── ateco.py             # ATECO code → profitability coefficient (forfettario)
│   ├── calculators/             # Financial calculators
│   │   ├── __init__.py
│   │   ├── cdq.py               # CdQ rata, capacity, renewal eligibility
│   │   ├── dti.py               # Debt-to-income ratio
│   │   └── income.py            # Income normalization (monthly equivalent)
│   ├── eligibility/             # Product matching engine
│   │   ├── __init__.py
│   │   ├── engine.py            # Main engine: profile → matched products
│   │   ├── rules.py             # Rule loader (from Excel/YAML)
│   │   ├── products.py          # Primo Network product definitions
│   │   └── suggestions.py       # Smart suggestions (consolidamento, rinnovo, etc.)
│   ├── dossier/                 # Lead dossier builder
│   │   ├── __init__.py
│   │   ├── builder.py           # Assembles full dossier from session data
│   │   └── quotation.py         # Maps to Primo Network's 3 form schemas
│   ├── channels/                # Messaging channel adapters
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract channel interface
│   │   ├── telegram.py          # Telegram user bot
│   │   └── whatsapp.py          # WhatsApp Business API
│   ├── admin/                   # Admin interface
│   │   ├── __init__.py
│   │   ├── bot.py               # Telegram admin bot
│   │   ├── web.py               # FastAPI admin routes
│   │   ├── alerts.py            # Alert rules and push notifications
│   │   ├── events.py            # Event emitter + listener system
│   │   └── templates/           # Jinja2 + HTMX templates
│   │       ├── base.html
│   │       ├── dashboard.html
│   │       ├── sessions.html
│   │       ├── session_detail.html
│   │       ├── pipeline.html
│   │       ├── health.html
│   │       └── gdpr.html
│   ├── scheduling/              # Appointment booking
│   │   ├── __init__.py
│   │   └── calcom.py            # Cal.com / Calendly integration
│   ├── llm/                     # LLM client wrapper
│   │   ├── __init__.py
│   │   ├── client.py            # Ollama client (OpenAI-compatible API)
│   │   ├── models.py            # Model definitions, loading strategy
│   │   └── context.py           # Context/prompt builder with token management
│   ├── security/                # Security & GDPR
│   │   ├── __init__.py
│   │   ├── encryption.py        # Field-level AES-256 encryption
│   │   ├── consent.py           # Consent management
│   │   ├── erasure.py           # Right to erasure (/elimina_dati) workflow
│   │   └── audit.py             # Audit logging
│   └── db/                      # Database
│       ├── __init__.py
│       ├── engine.py            # Async engine + session factory
│       └── migrations.py        # Alembic helpers
├── data/
│   ├── ateco_coefficients.json  # ATECO → forfettario profitability coefficients
│   ├── cadastral_codes.json     # CF birthplace codes → municipality names
│   ├── eligibility_rules.xlsx   # Operator-editable product rules
│   └── prompts/                 # External prompt templates (if preferred over Python)
├── tests/
│   ├── conftest.py
│   ├── test_cf_decoder.py
│   ├── test_cdq_calculator.py
│   ├── test_dti_calculator.py
│   ├── test_eligibility.py
│   ├── test_fsm.py
│   ├── test_ocr_validators.py
│   └── test_conversation/
│       └── test_scenarios.py    # End-to-end conversation test scenarios
└── scripts/
    ├── setup_ollama.sh          # Download and configure Ollama models
    ├── seed_db.py               # Seed database with initial data
    └── generate_test_data.py    # Generate test payslips/cedolini for development
```

## Key Design Decisions

1. **FSM backbone + LLM responses:** The finite state machine controls flow and data collection. The LLM generates natural Italian responses within the constraints of each state. Never let the LLM make financial decisions — only the rules engine and calculators do that.

2. **Sequential model loading (MVP):** On 16GB M2, only one model fits in memory. Conversation model (Qwen3 8B) is active by default. When a document is received, unload conversation model, load vision model (Qwen2.5-VL 7B), process, then swap back. ~10–15s cold-start.

3. **Everything is an event:** Every action emits a `SystemEvent` that feeds the audit log, admin bot, and web dashboard simultaneously. This is core infrastructure, not an afterthought.

4. **Deterministic over LLM:** CF decoding, CdQ calculations, DTI ratios, eligibility rules — all pure Python with unit tests. The LLM is only used for natural language understanding and generation, never for math or decisions.

5. **Source tracking:** Every data field records its source (ocr, ocr_confirmed, cf_decode, manual, computed, api, self_declared). This feeds the dossier confidence levels and audit trail.

## Coding Standards

- Type hints everywhere. Use `from __future__ import annotations`.
- Pydantic v2 models for all external data boundaries.
- Async by default (asyncio, async SQLAlchemy, async Redis).
- Structured logging (JSON format via `structlog`).
- Tests for all calculators, decoders, and eligibility rules.
- Italian text in prompts and user-facing messages; English in code and comments.
- All financial amounts as `Decimal`, never `float`.
- Docstrings on all public functions and classes.

## Environment Variables

```env
# LLM
OLLAMA_BASE_URL=http://localhost:11434
CONVERSATION_MODEL=qwen3:8b-q4_K_M
VISION_MODEL=qwen2.5-vl:7b-q4_K_M

# Database
DATABASE_URL=postgresql+asyncpg://brokerbot:password@localhost:5432/brokerbot
REDIS_URL=redis://localhost:6379/0

# Telegram
TELEGRAM_USER_BOT_TOKEN=...
TELEGRAM_ADMIN_BOT_TOKEN=...
ADMIN_TELEGRAM_IDS=123456789  # comma-separated

# WhatsApp (Phase 1b)
WHATSAPP_API_URL=...
WHATSAPP_API_TOKEN=...

# Scheduling
CALCOM_API_URL=...
CALCOM_API_KEY=...

# Security
ENCRYPTION_KEY=...           # 32-byte AES key, base64 encoded
JWT_SECRET=...               # For admin web auth (Phase 2)
ADMIN_WEB_PASSWORD=...       # HTTP Basic Auth (Phase 1)

# Branding
BOT_NAME=ameconviene.it
LEGAL_ENTITY=Primo Network Srl
OAM_NUMBER=M94
TOLL_FREE=800.99.00.90
```

## How to Work with This Project

1. **Before coding any module,** read the relevant section of `docs/PRD_v1.5.md`.
2. **Start with the foundation:** models, DB, config, event system, LLM client.
3. **Build bottom-up:** decoders/calculators (testable, no dependencies) → eligibility engine → OCR pipeline → conversation engine → channels → admin.
4. **Test calculators first** — they're pure functions with known inputs/outputs.
5. **The FSM is the backbone** — get it right before layering LLM responses.
6. **Admin is not Phase 2** — the event system and Telegram admin bot are built in Week 1–2.

## Agent System

This project uses specialized agents (see `/agents/` directory). Each agent has deep knowledge of its subsystem and can be invoked for focused tasks. Use `/agents/README.md` for the full list and when to invoke each one.

## Important Files to Read First

1. This file (CLAUDE.md)
2. `docs/PRD_v1.5.md` — Sections 3 (Products), 5 (Flow), 7 (Quotation Fields), 11 (Eligibility), 12 (Admin), 14 (Compliance)
3. `agents/README.md` — Agent system overview
