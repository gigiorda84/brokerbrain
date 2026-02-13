# Agent: Conversation

## Domain
Finite state machine, state handlers, LLM prompt engineering, Italian UX, message flow orchestration.

## Context
The conversation engine is the brain of BrokerBot. It receives messages from channel adapters, determines the current state, builds the LLM prompt, parses the response, extracts structured data, and transitions to the next state. The FSM ensures the conversation stays on track; the LLM makes it feel natural in Italian.

## Key Decisions

### FSM Architecture
- States are an enum. Transitions are defined as a dict: `{State: {trigger: NextState}}`.
- Each state has a **handler class** with: `build_prompt()`, `parse_response()`, `validate()`, `extract_data()`, `get_transitions()`.
- The orchestrator (`engine.py`) does: load session → get handler for current state → build prompt with context → call LLM → parse → validate → store data → transition → respond.
- The LLM response must include a JSON action block for state transitions and data extraction. Use a structured output approach: instruct the LLM to end its Italian response with a `---` separator followed by a JSON block.

### LLM Response Format
```
[Natural Italian response to the user]
---
{"action": "transition", "next_state": "LIABILITIES_INTRO", "data": {"employment_type": "dipendente", "employer_category": "pubblico"}}
```
Or for data collection without transition:
```
[Natural Italian response asking for more info]
---
{"action": "collect", "data": {"net_salary": 1750}}
```
Or when the user's message is unclear:
```
[Clarification question in Italian]
---
{"action": "clarify", "reason": "employment_type_unclear"}
```

The orchestrator parses the JSON block, strips it from the user-visible response, and acts on the action.

### State List (18 states)
```
WELCOME → CONSENT → NEEDS_ASSESSMENT → EMPLOYMENT_TYPE
→ EMPLOYER_CLASS_DIP / PENSION_CLASS
→ TRACK_CHOICE_EMP / TRACK_CHOICE_PIV / TRACK_CHOICE_PEN
→ DOC_REQUEST_* / MANUAL_*
→ DOC_PROCESSING_*
→ HOUSEHOLD_DATA → LIABILITIES_INTRO → LIABILITIES_DETAIL → LIABILITIES_DOC
→ PRODUCT_MATCHING → RESULT_ELIGIBLE / RESULT_PARTIAL / RESULT_NOT_ELIGIBLE
→ SCHEDULING → CONFIRMATION → END
+ HUMAN_ESCALATION (from any state)
```

### Prompt Design Principles
1. **System prompt per state:** Each state has a dedicated system prompt that defines the bot's goal, available data, valid actions, and output format.
2. **Context injection:** The orchestrator injects: current state, employment type, all collected data so far, available transitions.
3. **Identity:** Every prompt starts with "Sei l'assistente digitale di ameconviene.it, servizio di Primo Network Srl (OAM M94)."
4. **Tone:** Formal "lei" register. Warm, professional, empathetic. Never judgmental about debt or unemployment.
5. **Disclaimers:** Injected at RESULT states: "Questa è una verifica preliminare..."
6. **Language:** All user-facing text in Italian. System prompts in English for better LLM instruction-following, but with Italian example outputs.

### Italian UX Details
- Use "lei" (formal), never "tu"
- Currency: €1.750,00 (dot for thousands, comma for decimals — Italian format)
- Dates: DD/MM/YYYY
- Phone: already collected from platform
- Don't use bullet points in conversation — use numbered options: "1. Veloce 2. Manuale"
- Emoji sparingly: 🚀 for fast track, 💬 for manual, ✅ for confirmation, ⚠️ for warnings
- Normalize sensitive topics: "Molte persone si trovano in questa situazione..."
- Primo Network contact always available: "Se preferisce, può chiamare 800.99.00.90"

### Conversation Commands (User)
- `/start` — begin conversation (Telegram)
- `/elimina_dati` — GDPR right to erasure
- `/i_miei_dati` — GDPR right of access
- `/aiuto` — help / restart options
- `/operatore` — request human escalation

## Dependencies
- `foundation` agent: models, DB, event system, LLM client
- `calculators` agent: called during PRODUCT_MATCHING state
- `ocr` agent: called during DOC_PROCESSING states
- `admin` agent: events emitted at every state transition

## Task Checklist
- [ ] `src/conversation/states.py` — State enum + transition map
- [ ] `src/conversation/fsm.py` — FSM class: current_state, transition(), can_transition()
- [ ] `src/conversation/engine.py` — Main orchestrator: process_message() → response
- [ ] `src/conversation/prompts/base.py` — Shared prompt components (identity, tone, format instructions)
- [ ] `src/conversation/prompts/consent.py` — CONSENT state prompt (GDPR + AI Act)
- [ ] `src/conversation/prompts/welcome.py` — WELCOME prompt
- [ ] `src/conversation/prompts/needs_assessment.py` — Product interest collection
- [ ] `src/conversation/prompts/employment_type.py` — Employment detection
- [ ] `src/conversation/prompts/employer_class.py` — Statale/pubblico/privato/parapubblico
- [ ] `src/conversation/prompts/pension_class.py` — INPS/INPDAP + ex-public check
- [ ] `src/conversation/prompts/track_choice.py` — Fast vs manual
- [ ] `src/conversation/prompts/doc_request.py` — Document upload instructions
- [ ] `src/conversation/prompts/manual_collection.py` — Q&A per employment type (4 variants)
- [ ] `src/conversation/prompts/household.py` — Nucleo familiare, percettori, provincia
- [ ] `src/conversation/prompts/liabilities.py` — Existing debts collection
- [ ] `src/conversation/prompts/result.py` — Eligibility result presentation (3 variants)
- [ ] `src/conversation/prompts/scheduling.py` — Appointment booking
- [ ] `src/conversation/handlers/` — Per-state logic for data extraction and validation
- [ ] Tests: FSM transitions, prompt building, response parsing, state handler logic
- [ ] Integration test: full conversation scenario (dipendente fast track)
