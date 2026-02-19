# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BrokerBot is an AI-powered lead qualification chatbot for **ameconviene.it** (Primo Network Srl, Italian credit brokerage, OAM M94). It qualifies consumers for 9 financial products (cessione del quinto, prestiti, mutui, TFS, insurance) via Telegram/WhatsApp using local LLMs (Ollama) for conversation and document OCR.

**Owner:** Giuseppe Giordano
**Legal entity:** Primo Network Srl (P.IVA 08154920014)
**Full PRD:** `docs/PRD_v1.5.md` — read relevant sections before working on any module.

## Development Commands

```bash
# Setup
pip install -e ".[dev]"
docker compose up -d                          # PostgreSQL 16 + Redis 7
scripts/setup_ollama.sh                       # Download Qwen3 8B + Qwen2.5-VL 7B

# Run
uvicorn src.main:app --reload                 # Dev server on :8000
python -m src.main                            # Production entry point

# Database
alembic upgrade head                          # Run migrations
alembic revision --autogenerate -m "desc"     # Generate migration

# Test
pytest                                        # All tests
pytest tests/test_cf_decoder.py -v            # Single test file
pytest tests/ --cov                           # With coverage

# Lint & Type Check
ruff check src/                               # Lint (line-length=120)
ruff check src/ --fix                         # Auto-fix
mypy src/                                     # Type check (strict mode)
```

## Architecture

```
User (Telegram/WhatsApp)
  → FastAPI webhook
    → Conversation Engine (FSM + Qwen3 8B via Ollama)
      → OCR Pipeline (Qwen2.5-VL 7B) — model-swapped on demand
      → CF Decoder / Calculators (pure Python, deterministic)
      → Eligibility Engine (rule-based product matching)
      → Dossier Builder (pre-fills Primo Network forms)
    → Admin Interface (Telegram bot + HTMX dashboard)
  → PostgreSQL + Redis
```

### Core Design Principles

1. **FSM controls flow, LLM generates text.** The finite state machine (`src/conversation/states.py`) enforces all transitions. The LLM (Qwen3 8B) only generates natural Italian responses — it never makes financial decisions.

2. **Deterministic over LLM.** CF decoding, CdQ/DTI calculations, eligibility rules are all pure Python with unit tests. No LLM for math or decisions.

3. **Sequential model loading.** On 16GB M2, only one model fits. Conversation model loads by default; vision model swaps in for OCR (~10-15s cold start), then swaps back.

4. **Event-driven everything.** Every action emits a `SystemEvent` feeding audit log, admin bot, and web dashboard simultaneously.

5. **Source tracking.** Every extracted data field records its `DataSource` (ocr, cf_decode, manual, computed, etc.) for dossier confidence and audit.

## Key Conventions

- **Type hints everywhere** with `from __future__ import annotations`
- **Pydantic v2** for all external data boundaries
- **Async throughout** — async SQLAlchemy, async Redis, async httpx for LLM
- **All money as `Decimal`**, never `float`. PostgreSQL `Numeric(12,2)` storage
- **Italian text** in prompts and user-facing messages; **English** in code and comments
- **Italian UX:** formal "lei" register, €1.750,00 formatting, DD/MM/YYYY dates, numbered options (not bullets)
- **Ruff rules:** E, F, I, N, UP, B, A, SIM at 120 char line length
- **Structured logging** via `structlog` (JSON format)
- **Field-level encryption** (AES-256-GCM) for sensitive data (CF, P.IVA, amounts)
- **TimestampMixin** on all models: UUID `id`, `created_at`, `updated_at`
- **JSONB** for flexible fields: `ocr_result`, `rule_results`, `confidence_scores`

## Agent System

Specialized agent docs live in `agents/`. Each covers a subsystem with context, architecture decisions, dependencies, and implementation tasks:

| Agent | Domain |
|---|---|
| `foundation.md` | DB models, config, event system, LLM client |
| `conversation.md` | FSM, state handlers, LLM prompts, Italian UX |
| `ocr.md` | Document processing pipeline |
| `calculators.md` | CF decoder, CdQ, DTI, income, eligibility |
| `admin.md` | Telegram admin bot, web dashboard, alerts |
| `channels.md` | Telegram/WhatsApp integration |
| `compliance.md` | GDPR, encryption, consent, audit, erasure |

Read the relevant agent file before working on that subsystem.

## Environment

Copy `.env.example` → `.env`. Key variables: `OLLAMA_BASE_URL`, `DATABASE_URL`, `REDIS_URL`, `TELEGRAM_USER_BOT_TOKEN`, `TELEGRAM_ADMIN_BOT_TOKEN`, `ADMIN_TELEGRAM_IDS`, `ENCRYPTION_KEY`. Full list in `src/config.py` (Pydantic Settings).
