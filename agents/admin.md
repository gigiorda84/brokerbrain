# Agent: Admin

## Domain
Telegram admin bot, FastAPI web dashboard, alert system, event subscribers, audit logging, dossier generation.

## Context
Giuseppe Giordano needs full visibility from day one. The admin interface has two channels: a Telegram bot for real-time push notifications and quick commands, and a lightweight web dashboard for deeper analysis. Both consume the same event stream.

## Key Decisions

### Telegram Admin Bot
- Separate Telegram bot instance (different token from user bot)
- Authorized users defined in env: `ADMIN_TELEGRAM_IDS=123456789,987654321`
- Every command checks authorization first
- Bot runs in the same FastAPI process (not a separate service)
- Uses python-telegram-bot's `Application` alongside the main FastAPI app

**Commands (17):**
```
/active         — List active conversations (state, duration, employment type)
/session <id>   — Full session detail (all data, calculations, matches)
/live <id>      — Subscribe to real-time updates for a session
/unlive <id>    — Unsubscribe from session updates
/today          — Today's summary (sessions, completions, bookings)
/week           — Weekly summary with breakdown
/alerts         — Current active alerts
/queue          — Pending appointments
/dossier <id>   — Generate and send lead dossier as formatted message
/search <query> — Search sessions by name, CF, or phone
/health         — System health (Ollama, DB, Redis, disk, memory)
/errors         — Errors in last 24h
/stats          — Quick KPIs (qualification rate, avg time, product mix)
/intervene <id> — Take over a conversation (→ HUMAN_ESCALATION)
/config         — View current configuration
/help           — List all commands
/gdpr           — GDPR status (pending deletions, consent overview)
```

### Alert System (`admin/alerts.py`)
Events flow through alert rules. Each rule checks conditions and optionally pushes to admin.

```python
ALERT_RULES = [
    AlertRule(
        name="new_eligible_lead",
        event_type="eligibility.decided",
        condition=lambda e: e.data.get("outcome") == "eligible",
        priority="high",
        template="🆕 Lead idoneo: {session_name} — {primary_product}",
    ),
    AlertRule(
        name="call_booked",
        event_type="appointment.booked",
        priority="medium",
        template="📅 Chiamata prenotata: {name} — {datetime} — {operator}",
    ),
    AlertRule(
        name="low_ocr_confidence",
        event_type="ocr.completed",
        condition=lambda e: any(v < 0.70 for v in e.data.get("confidence", {}).values()),
        priority="medium",
        template="⚠️ OCR bassa confidenza: sessione #{session_id} — {low_fields}",
    ),
    AlertRule(
        name="ocr_failure",
        event_type="error.occurred",
        condition=lambda e: e.data.get("error_type") == "ocr_extraction_failed",
        priority="high",
        template="🔴 OCR fallito: sessione #{session_id}",
    ),
    AlertRule(
        name="llm_timeout",
        event_type="llm.response",
        condition=lambda e: e.data.get("latency_ms", 0) > 30000,
        priority="high",
        template="🔴 LLM timeout: {model} — {latency_ms}ms",
    ),
    AlertRule(
        name="human_escalation",
        event_type="session.state_changed",
        condition=lambda e: e.data.get("to_state") == "HUMAN_ESCALATION",
        priority="high",
        template="👤 Escalation: sessione #{session_id} — {reason}",
    ),
    AlertRule(
        name="data_deletion",
        event_type="data_deletion.requested",
        priority="high",
        template="🔒 Richiesta eliminazione dati: utente #{user_id}",
    ),
    AlertRule(
        name="daily_digest",
        schedule="09:00",  # daily cron, not event-driven
        priority="low",
    ),
]
```

### Web Dashboard (`admin/web.py`)
- FastAPI routes mounted at `/admin/`
- Jinja2 templates + HTMX for interactivity (no React/Vue, no build step)
- HTTP Basic Auth in Phase 1, JWT+2FA in Phase 2
- HTMX: live-update session list every 10s, polling for new events

**Routes:**
```python
@admin_app.get("/")                    # Dashboard: active sessions, today stats, alerts
@admin_app.get("/sessions")            # Paginated session list with filters
@admin_app.get("/session/{id}")        # Full session detail
@admin_app.get("/session/{id}/raw")    # Raw LLM prompts/responses
@admin_app.get("/session/{id}/pipeline")  # Step-by-step pipeline view
@admin_app.get("/session/{id}/document/{doc_id}")  # View document + OCR overlay
@admin_app.get("/analytics")           # Charts (use Chart.js via CDN)
@admin_app.get("/health")              # System status
@admin_app.get("/audit")               # Audit log viewer
@admin_app.get("/gdpr")                # GDPR management
@admin_app.get("/rules")               # Eligibility rules viewer
@admin_app.post("/rules/upload")       # Upload updated rules file
```

### Dossier Builder (`dossier/builder.py`)
Generates the lead dossier that maps to Primo Network's quotation forms.

Sections: Anagrafica → Situazione Lavorativa → Nucleo Familiare → Impegni Finanziari → Calcoli → Prodotti Compatibili → Dati Pre-Compilati (per-form) → Documenti → Transcript.

Output formats:
- Formatted Telegram message (for `/dossier` command)
- HTML (for web dashboard)
- JSON (for future API submission to Primo Network)

### Event Subscribers
The event system has three subscribers, all registered at startup:

```python
async def setup_event_subscribers(event_bus: EventBus):
    event_bus.subscribe(AuditLogSubscriber(db))     # Writes every event to AuditLog table
    event_bus.subscribe(AdminBotSubscriber(admin_bot))  # Pushes alerts to Telegram
    event_bus.subscribe(MetricsSubscriber(prometheus))   # Updates Prometheus counters
```

## Dependencies
- `foundation` agent: event system, models, DB
- All other agents emit events that admin consumes

## Task Checklist
- [ ] `src/admin/events.py` — EventBus (pub/sub), SystemEvent model, subscribe/publish
- [ ] `src/security/audit.py` — AuditLogSubscriber (writes to DB)
- [ ] `src/admin/bot.py` — Telegram admin bot setup + all 17 commands
- [ ] `src/admin/alerts.py` — Alert rules, AlertEngine subscriber, push to Telegram
- [ ] `src/admin/web.py` — FastAPI admin routes + Basic Auth middleware
- [ ] `src/admin/templates/base.html` — Base template with HTMX, Tailwind CDN
- [ ] `src/admin/templates/dashboard.html` — Active sessions, stats, alerts
- [ ] `src/admin/templates/sessions.html` — Session list with filters
- [ ] `src/admin/templates/session_detail.html` — Full session view
- [ ] `src/admin/templates/pipeline.html` — Step-by-step processing view
- [ ] `src/admin/templates/health.html` — System status
- [ ] `src/admin/templates/gdpr.html` — GDPR management
- [ ] `src/dossier/builder.py` — Dossier assembly from session data
- [ ] `src/dossier/quotation.py` — Map to Primo Network's 3 form schemas
- [ ] Tests: alert rule evaluation, dossier generation, admin authorization
