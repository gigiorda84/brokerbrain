# BrokerBot — Product Requirements Document v1.5

**AI-Powered Lead Qualification Chatbot — ameconviene.it**

| Field | Value |
|---|---|
| Version | 1.5 |
| Date | February 2026 |
| Author | Giuseppe Giordano |
| Consumer Brand | ameconviene.it |
| Legal Entity | Primo Network Srl — Mediatore Creditizio (OAM M94) |
| Status | Draft |
| Classification | Confidential |

**Changelog:**
- **v1.5:** Updated branding to ameconviene.it / authorship to Giuseppe Giordano. Added comprehensive regulatory compliance framework (EU AI Act, GDPR, NIS2, Italian Privacy Code, Banca d'Italia, D.Lgs. 141/2010). Added Phase 1 Admin Interface for real-time monitoring of data collection, processing, and output. Restructured security section with compliance roadmap.
- **v1.4:** Aligned to Primo Network's product catalog (9 products), quotation form fields, CdQ sub-types, household data, TFS, Credito Assicurativo.
- **v1.3:** Pensionato/disoccupato paths, liabilities, DTI, CdQ rinnovo.
- **v1.2:** Partita IVA path, forfettario coefficients.
- **v1.1:** Dual-track flow, CF decoding, OCR pipeline.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Stakeholders & Branding](#2-stakeholders--branding)
3. [Product Catalog — Privati](#3-product-catalog--privati)
4. [System Architecture](#4-system-architecture)
5. [Conversational Flow Design](#5-conversational-flow-design)
6. [Employment-Type Branching](#6-employment-type-branching)
7. [Data Collection — Quotation Fields](#7-data-collection--quotation-fields)
8. [Existing Financial Liabilities Assessment](#8-existing-financial-liabilities-assessment)
9. [OCR Pipeline — Document Processing](#9-ocr-pipeline--document-processing)
10. [Codice Fiscale Decoding](#10-codice-fiscale-decoding)
11. [Eligibility Engine & Product Matching](#11-eligibility-engine--product-matching)
12. [Admin Interface — Phase 1](#12-admin-interface--phase-1)
13. [Scheduling & Human Handoff](#13-scheduling--human-handoff)
14. [Regulatory Compliance & Legal Framework](#14-regulatory-compliance--legal-framework)
15. [Security & Privacy — Technical Implementation](#15-security--privacy--technical-implementation)
16. [Technology Stack & Infrastructure](#16-technology-stack--infrastructure)
17. [Data Model](#17-data-model)
18. [Development Roadmap](#18-development-roadmap)
19. [Risks & Mitigations](#19-risks--mitigations)
20. [Success Metrics & KPIs](#20-success-metrics--kpis)
21. [Appendix](#21-appendix)

---

## 1. Executive Summary

BrokerBot is a conversational AI chatbot operating under the consumer brand **ameconviene.it**, built for **Primo Network Srl** (mediatore creditizio, OAM M94, Via Vandalino 49, Turin). It qualifies leads and collects the exact data needed for Primo Network's quotation systems, covering all 9 consumer products: cessione del quinto (stipendio and pensione), delega di pagamento, prestito personale, mutuo (acquisto, surroga, consolidamento), anticipo TFS, and credito assicurativo.

The system runs entirely on local infrastructure using open-source LLMs, handling four employment categories (dipendente, partita IVA, pensionato, disoccupato), assessing existing liabilities for DTI calculation, and producing pre-filled lead dossiers mapped to Primo Network's quotation forms.

**Regulatory posture:** The system is designed to comply with the EU AI Act (Reg. 2024/1689), GDPR (Reg. 2016/679), NIS2 Directive (2022/2555), Italian Privacy Code (D.Lgs. 196/2003 as amended), Banca d'Italia transparency requirements, and D.Lgs. 141/2010 on credit intermediation. Full compliance assessment is planned as a dedicated workstream — this PRD documents the architectural decisions that enable compliance.

**Admin oversight:** From Phase 1, an admin interface provides Giuseppe Giordano and authorized operators with real-time visibility into all conversations, data collection, OCR processing, eligibility decisions, and system health — directly via Telegram admin bot and a lightweight web dashboard.

### Key Targets

| Metric | Target |
|---|---|
| Lead qualification time | < 5 min (fast track) / < 10 min (manual) |
| Document processing accuracy | > 95% |
| Data completeness for quotation | > 90% of required fields |
| Eligible lead → call booking | > 70% |
| System availability | 99.5% |
| Data residency | 100% EU, 100% local LLM |
| Admin alert latency | < 60 seconds |

---

## 2. Stakeholders & Branding

### 2.1 Brand Architecture

| Layer | Entity | Role |
|---|---|---|
| Consumer brand | **ameconviene.it** | User-facing name, chatbot identity, marketing |
| Legal / regulatory entity | **Primo Network Srl** | OAM-registered mediatore creditizio, responsible for all lending activity |
| Project owner | **Giuseppe Giordano** | Product owner, system administrator, lead developer |

**How it works for the user:** The chatbot introduces itself as ameconviene.it, a service powered by Primo Network. All regulatory disclosures reference Primo Network Srl as the responsible entity (OAM M94, IVASS E000294291). This is similar to how many Italian financial services operate — consumer brand backed by a regulated entity.

### 2.2 About Primo Network Srl

- **OAM Registration:** M94 (Organismo degli Agenti e dei Mediatori)
- **IVASS:** E000294291
- **Headquarters:** Via Vandalino 49, 10142 Torino
- **Contact:** 800.99.00.90 (toll-free), 011.3988911, info@primonetwork.it
- **Legal:** Cap. Soc. €228,000 i.v., REA TO-950567, CF/P.IVA 08154920014
- **PEC:** posta.certificata@pec.primonetwork.it

### 2.3 Chatbot Identity

```
Name:       ameconviene.it assistant
Tagline:    "Il confronto che ti conviene"
Tone:       Warm, professional, empathetic. Formal "lei" register.
Language:   Italian (primary), future: multilingual
Regulatory: "Servizio offerto da Primo Network Srl, mediatore creditizio
             iscritto all'OAM al n. M94"
```

### 2.4 Roles & Access Levels

| Role | Person(s) | Access |
|---|---|---|
| **System Admin** | Giuseppe Giordano | Full: all conversations, all data, system config, model management, logs, deployments |
| **Operator** | Primo Network consultants | Lead dossiers, appointment management, document review for assigned leads |
| **Supervisor** | Primo Network management | Analytics, aggregated KPIs, compliance reports, no individual conversation access unless escalated |
| **User** | Consumer | Own conversation, own data, deletion rights |

---

## 3. Product Catalog — Privati

*(Unchanged from v1.4 — all 9 products with sub-types. See v1.4 Section 3 for full details.)*

### 3.1 Product Overview

| # | Product | Customer Types | Key Feature |
|---|---|---|---|
| 1 | CdQ Stipendio | Dipendenti (statali/pubblici/privati/parapubblici) | Max 1/5 net salary, payroll deduction |
| 2 | CdQ Pensione | Pensionati (INPS/INPDAP) | Max 1/5 net pension |
| 3 | Delega | Dipendenti | Additional 1/5 alongside CdQ |
| 4 | Prestito Personale | All with income | €1,500–€50,000, up to 120 months |
| 5 | Mutuo Acquisto | All with income | Up to 100% with Consap |
| 6 | Mutuo Surroga | Existing mortgage holders | Transfer to better rate, zero cost |
| 7 | Mutuo Consolidamento | Those with multiple debts | Unify debts into single mortgage |
| 8 | Anticipo TFS | Retired ex-public/state | Advance on severance pay |
| 9 | Credito Assicurativo | Anyone with a loan | Repayment protection insurance |

### 3.2 CdQ Sub-Types (10 variants)

**CdQ Stipendio:** Dipendente Statale, Dipendente Pubblico, Dipendente Azienda Privata, Dipendente Parapubblico.

**CdQ Pensione:** Pensionato INPS/ALTRO, Pensionato INPDAP.

**Delega:** Dipendente Statale, Dipendente Pubblico, Dipendente Azienda Privata, Dipendente Parapubblico.

### 3.3 Product Eligibility Matrix

| Product | Dipendente | P.IVA | Pensionato | Disoccupato |
|---|---|---|---|---|
| CdQ Stipendio | ✅ | ❌ | ❌ | ❌ |
| CdQ Pensione | ❌ | ❌ | ✅ | ❌ |
| Delega | ✅ | ❌ | ❌ | ❌ |
| Prestito Personale | ✅ | ✅ | ✅ | ⚠️ garante |
| Mutuo Acquisto | ✅ | ✅ | ✅ | ❌ |
| Mutuo Surroga | ✅ | ✅ | ✅ | ❌ |
| Mutuo Consolidamento | ✅ | ✅ | ✅ | ❌ |
| Anticipo TFS | ❌ | ❌ | ✅ ex-pub | ❌ |
| Credito Assicurativo | ✅ | ✅ | ✅ | ❌ |

### 3.4 CdQ Business Rules (from Primo Network)

- Available even with disguidi finanziari, cattivi pagatori, pignoramenti
- Duration: 24–120 months
- Renewal after 40% paid (exception: first CdQ 60→120)
- Prefinanziamento up to 50% in ~1 week
- Guarantees: rischio impiego + rischio vita insurance (included)
- CdQ + Delega = max 2/5 of net salary (dipendenti only)
- Pensionati: only CdQ, no Delega; max age 85 at maturity
- Job loss: covered by mandatory insurance → TFR first, then insurance

---

## 4. System Architecture

### 4.1 Overview

| Layer | Component | Technology |
|---|---|---|
| Messaging | Channel adapters | WhatsApp Business API, Telegram Bot API |
| Conversation | Orchestrator + LLM | Python (FastAPI) + Ollama (Qwen3 8B) |
| OCR | Document processor | Ollama (Qwen2.5-VL 7B) + Surya |
| CF Decoder | Tax ID parser | Pure Python |
| Calculators | DTI, CdQ rata/capacity/renewal | Pure Python |
| Eligibility | Rules + product matching | Python + Pandas |
| **Admin** | **Monitoring + management** | **Telegram Admin Bot + FastAPI dashboard** |
| Data | State & persistence | PostgreSQL + Redis |
| Scheduling | Appointments | Cal.com / Calendly |
| Logging | Audit trail | Structured logs + PostgreSQL |
| Monitoring | System health | Prometheus + Grafana |

### 4.2 Data Flow

```
[User on WhatsApp/Telegram]
    │
    ▼
[Conversation Engine] ── State machine + LLM
    │                              │
    │                    ┌─────────┴──────────┐
    │                    ▼                    ▼
    │              [Admin Interface]    [Audit Logger]
    │              (real-time view)    (every event)
    │
    ▼
[Employment Type → Employer/Pension Classification]
    │
    ├─ DIPENDENTE ──→ Payslip OCR or Q&A → employer_category
    ├─ PARTITA IVA ──→ Dichiarazione OCR or Q&A → tax regime
    ├─ PENSIONATO ──→ Cedolino OCR or Q&A → pension_source + TFS check
    └─ DISOCCUPATO ──→ NASpI/guarantor Q&A
    │
    ▼
[CF Decoder] → [Household Data] → [Liabilities Assessment]
    │
    ▼
[DTI & CdQ Calculators]
    │
    ▼
[Product Matching] ── Match to 9 Primo Network products
    │                              │
    │                    ┌─────────┴──────────┐
    │                    ▼                    ▼
    │              [Admin Alert]        [Dossier Builder]
    │              (new qualified lead)  (pre-filled forms)
    ▼
[Scheduling] → [Confirmation] → [Operator receives dossier]
```

### 4.3 LLM Strategy

| Function | Model | Quantization | RAM |
|---|---|---|---|
| Conversation | Qwen3 8B | Q4_K_M | ~6 GB |
| OCR / Vision | Qwen2.5-VL 7B | Q4_K_M | ~6 GB |

Sequential on 16GB M2 (MVP), concurrent on 32GB+ (production).

---

## 5. Conversational Flow Design

### 5.1 State Machine

| State | Purpose | Transitions To |
|---|---|---|
| `WELCOME` | Greet as ameconviene.it, Primo Network disclosure | `CONSENT` |
| `CONSENT` | Collect GDPR + AI Act transparency consents | `NEEDS_ASSESSMENT` |
| `NEEDS_ASSESSMENT` | Product interest, amount, urgency | `EMPLOYMENT_TYPE` |
| `EMPLOYMENT_TYPE` | Dipendente / P.IVA / Pensionato / Disoccupato | `EMPLOYER_CLASS_*` / `TRACK_CHOICE_*` |
| `EMPLOYER_CLASS_DIP` | Statale / Pubblico / Privato / Parapubblico | `TRACK_CHOICE_EMP` |
| `PENSION_CLASS` | INPS / INPDAP + ex-public/state for TFS | `TRACK_CHOICE_PEN` |
| `TRACK_CHOICE_*` | Fast (document upload) or manual Q&A | `DOC_*` / `MANUAL_*` |
| `DOC_REQUEST_*` | Ask for document | `DOC_PROCESSING_*` |
| `DOC_PROCESSING_*` | OCR + CF decode + confirmation | `HOUSEHOLD_DATA` |
| `MANUAL_*` | Q&A per type | `HOUSEHOLD_DATA` |
| `HOUSEHOLD_DATA` | Nucleo familiare, percettori reddito, provincia | `LIABILITIES_INTRO` |
| `LIABILITIES_INTRO` | Ask about existing debts | `LIABILITIES_DETAIL` / `PRODUCT_MATCHING` |
| `LIABILITIES_DETAIL` | Each liability's details | `LIABILITIES_DOC` / `PRODUCT_MATCHING` |
| `LIABILITIES_DOC` | Optional supporting docs | `PRODUCT_MATCHING` |
| `PRODUCT_MATCHING` | DTI + CdQ calc + rules → match products | `RESULT_*` |
| `RESULT_ELIGIBLE` | Present matching products | `SCHEDULING` |
| `RESULT_PARTIAL` | Conditional eligibility | `SCHEDULING` |
| `RESULT_NOT_ELIGIBLE` | Explain, suggest alternatives | `END` |
| `SCHEDULING` | Book call with Primo Network consultant | `CONFIRMATION` |
| `CONFIRMATION` | Confirm booking, send summary | `END` |
| `HUMAN_ESCALATION` | Transfer to live agent | `END` |

### 5.2 CONSENT State — Regulatory Requirements

This state is mandatory before any data collection. It satisfies GDPR Art. 13/14, the EU AI Act Art. 50 transparency obligation, and Primo Network's own 4-consent structure.

```
Bot: "Benvenuto/a su ameconviene.it, il servizio di confronto
     finanziario offerto da Primo Network Srl (mediatore creditizio,
     OAM M94).

     Prima di procedere, alcune informazioni importanti:

     🤖 Sta parlando con un assistente basato su intelligenza
     artificiale. Le decisioni finali sono sempre prese da un
     consulente umano di Primo Network.

     🔒 I suoi dati sono trattati localmente e non vengono inviati
     a servizi cloud esterni. Il titolare del trattamento è
     Primo Network Srl (privacy@primonetwork.it).

     Per procedere, ho bisogno del suo consenso:
     ✅ Trattamento dati per finalità contrattuali (obbligatorio)
     ✅ Trattamento dati particolari/sensibili (obbligatorio)

     Acconsente? Può revocare il consenso in qualsiasi momento
     scrivendo /elimina_dati."
```

**Key AI Act requirements addressed here:**
- Art. 50(1): Inform user they are interacting with an AI system
- Art. 50(3): Mark AI-generated content appropriately
- Human oversight disclosure: final decisions by human consultant

### 5.3 Welcome & Branding

```
Bot: "Perfetto, grazie! Sono l'assistente di ameconviene.it.
     Confronto per lei i tassi dei migliori istituti di credito
     per trovare la soluzione più conveniente.

     Posso aiutarla con: cessione del quinto, prestiti personali,
     mutui, consolidamento debiti, anticipo TFS e molto altro.

     Per quale esigenza posso assisterla?

     (Se preferisce parlare con un consulente, chiami il numero
     verde 800.99.00.90 o scriva a info@primonetwork.it)"
```

---

## 6. Employment-Type Branching

*(Unchanged from v1.4. Full details: employer classification for dipendenti — statale/pubblico/privato/parapubblico; pension classification for pensionati — INPS/INPDAP + ex-public for TFS; P.IVA with forfettario/ordinario; disoccupato with NASpI/guarantor assessment.)*

---

## 7. Data Collection — Quotation Fields

*(Unchanged from v1.4. Maps field-by-field to Primo Network's three quotation forms: CQS calculator, Mutuo calculator, Generic quote form. Includes household data — nucleo familiare, percettori reddito, provincia immobile.)*

---

## 8. Existing Financial Liabilities Assessment

*(Unchanged from v1.4. Liabilities collection, CdQ detection from payslip/cedolino, CdQ renewal check (40% rule), DTI calculation, consolidamento suggestion, optional conteggio estintivo upload.)*

---

## 9. OCR Pipeline — Document Processing

*(Unchanged from v1.4. OCR prompts for: busta paga, cedolino pensione, dichiarazione dei redditi, conteggio estintivo/piano ammortamento, document classification.)*

---

## 10. Codice Fiscale Decoding

*(Unchanged from v1.4. Pure Python CF decoder: birthdate, age, gender, birthplace from 16-char code.)*

---

## 11. Eligibility Engine & Product Matching

*(Unchanged from v1.4. Rules per employment type, CdQ-specific rules from Primo Network, mutuo rules, eligibility outcomes, smart suggestions.)*

---

## 12. Admin Interface — Phase 1

This is a critical addition. From day one, Giuseppe Giordano needs full visibility into what the system is doing. The Phase 1 admin interface is lightweight but comprehensive, operating through two channels: a Telegram Admin Bot and a minimal FastAPI web dashboard.

### 12.1 Design Principles

- **Real-time visibility:** Every conversation event, OCR extraction, eligibility decision, and error is visible within 60 seconds
- **No blind spots:** The admin sees everything the user sees, plus internal processing (LLM prompts/responses, confidence scores, rule evaluations)
- **Actionable alerts:** Critical events trigger push notifications, not just passive logs
- **Minimal overhead:** Built into the core system from the start, not bolted on later
- **Audit-ready:** All admin actions are logged (who viewed what, when)

### 12.2 Telegram Admin Bot

A separate Telegram bot for admin use. Only authorized users (Giuseppe + approved operators) can access it.

**Commands:**

| Command | Function | Example Output |
|---|---|---|
| `/active` | List active conversations | "3 active sessions: #142 (Maria, dipendente, DOC_PROCESSING), #143 (Luca, pensionato, LIABILITIES), #144 (Sara, P.IVA, MANUAL)" |
| `/session <id>` | Full session detail | All collected data, current state, timeline, documents |
| `/live <id>` | Subscribe to live updates for a session | Push messages for each state transition, OCR result, decision |
| `/today` | Today's summary | "Sessions: 12 started, 8 completed, 5 eligible, 3 calls booked" |
| `/week` | Weekly summary | Breakdown by product, employment type, conversion rates |
| `/alerts` | Current active alerts | "⚠️ Session #142: OCR confidence < 70% on salary field" |
| `/queue` | Pending appointments | "3 calls scheduled: today 15:00 (Marco), tomorrow 10:00 (Laura), ..." |
| `/dossier <id>` | Generate and send dossier | PDF or formatted message with all lead data |
| `/search <name\|CF>` | Search past sessions | Find by user name or codice fiscale |
| `/health` | System health | LLM status, DB connection, queue depth, memory usage |
| `/errors` | Recent errors | Last 24h: OCR failures, LLM timeouts, API errors |
| `/stats` | Quick KPIs | Qualification rate, avg time, DTI distribution, product mix |
| `/intervene <id>` | Take over a conversation | Transitions session to HUMAN_ESCALATION, admin responds directly |
| `/config` | View current config | Active rules, model versions, thresholds |

**Alert Types (Push Notifications):**

| Alert | Trigger | Priority |
|---|---|---|
| 🆕 New eligible lead | Session reaches RESULT_ELIGIBLE | High |
| 📅 Call booked | Appointment confirmed | Medium |
| ⚠️ Low OCR confidence | Any field confidence < 70% | Medium |
| ⚠️ High DTI | DTI > 40% | Low |
| 🔴 OCR failure | 2 consecutive extraction failures | High |
| 🔴 LLM timeout | Response time > 30s | High |
| 🔴 System error | Unhandled exception | Critical |
| 👤 Human escalation | User requests human or bot can't proceed | High |
| 🔒 Data deletion request | User sends /elimina_dati | High |
| 📊 Daily digest | Every day at 09:00 | Low |

**Authorization:**

```python
ADMIN_USERS = {
    "giuseppe_giordano_telegram_id": {
        "role": "system_admin",
        "permissions": ["all"]
    },
    # Additional operators can be added
}

async def verify_admin(telegram_user_id: int) -> bool:
    """Verify the user is authorized for admin access."""
    return str(telegram_user_id) in ADMIN_USERS
```

### 12.3 Web Dashboard (Lightweight FastAPI)

A simple, password-protected web interface for deeper analysis. Not a full Next.js app — just server-rendered HTML with HTMX for interactivity (no frontend build step).

**Pages:**

| Page | Content |
|---|---|
| `/admin/` | Dashboard: active sessions, today's stats, recent alerts |
| `/admin/sessions` | Paginated list of all sessions with filters (date, status, employment type, product) |
| `/admin/session/<id>` | Full session detail: conversation transcript, collected data, OCR results with confidence, documents (viewable), eligibility evaluation, dossier |
| `/admin/session/<id>/raw` | Raw LLM prompts/responses for debugging |
| `/admin/pipeline/<id>` | Visual pipeline view: each processing step with input/output/timing |
| `/admin/analytics` | Charts: daily volume, conversion funnel, product distribution, DTI histogram, avg processing time |
| `/admin/documents/<id>` | View uploaded document with OCR overlay showing extracted fields |
| `/admin/rules` | Current eligibility rules (from Excel), ability to download/upload updated rules file |
| `/admin/health` | System status: Ollama models loaded, DB pool, Redis, queue depth, disk space |
| `/admin/audit` | Audit log: all admin actions (who viewed what session, when) |
| `/admin/gdpr` | GDPR dashboard: pending deletion requests, consent status, data retention overview |

**Authentication:**

Phase 1: HTTP Basic Auth over HTTPS (simple, sufficient for single admin). Phase 2: proper auth with JWT + 2FA.

### 12.4 Session Detail View — What the Admin Sees

For each session, the admin can view:

```
SESSION #142 — Maria Rossi
━━━━━━━━━━━━━━━━━━━━━━━━━
Status:       ELIGIBLE → SCHEDULING
Duration:     4m 32s
Track:        Fast (payslip upload)
Employment:   Dipendente — Azienda Privata
Employer:     XYZ Srl

── COLLECTED DATA ──────────────────────────────
Field                 Value              Source        Confidence
full_name             Maria Rossi        ocr_confirmed  0.98
codice_fiscale        RSSMRA85H52F205R   ocr_confirmed  0.99
→ age                 40                 cf_decode      1.00
→ gender              F                  cf_decode      1.00
→ birthplace          Milano             cf_decode      1.00
employer_name         XYZ Srl            ocr_confirmed  0.95
employer_category     Privato            manual         1.00
contract_type         Indeterminato      ocr            0.88
hiring_date           15/03/2019         ocr            0.82  ⚠️
net_salary            €1.750             ocr_confirmed  0.97
email                 maria@email.com    manual         1.00
provincia_residenza   Torino             manual         1.00
nucleo_familiare      3                  manual         1.00
percettori_reddito    2                  manual         1.00

── LIABILITIES ─────────────────────────────────
Type               Rata    Remaining   Residual   Lender      Source
Prestito personale €180    36 mesi     €5.800     Findomestic manual
Finanziamento auto €220    18 mesi     €3.600     Agos        manual
TOTAL              €400/mese

── CALCULATIONS ────────────────────────────────
CdQ max rata:        €350 (€1.750/5)
CdQ existing:        €0
CdQ available:       €350
Delega available:    €350
DTI current:         22.9% (€400/€1.750)
DTI projected:       (depends on product)

── PRODUCT MATCHING ────────────────────────────
1. ✅ CdQ Dipendente Azienda Privata — rata max €350, 120 mesi
2. ✅ Prestito Personale — €1.500-€50.000
3. ✅ Delegazione Dipendente Azienda Privata — rata max €350
4. 💡 Consolidamento — unifica 2 finanziamenti (DTI 22.9%)
5. 🛡️ Credito Assicurativo (cross-sell)

── QUOTATION DATA (PRE-FILLED) ─────────────────
CQS Form: nascita=1985-06-12, prodotto=CdQ_Dip_Privato,
          rata=350, durata=120, assunzione=2019-03-15,
          nome=Maria, cognome=Rossi, email=maria@email.com,
          cell=(from WhatsApp)

── DOCUMENTS ───────────────────────────────────
📄 Busta paga (2025-01) — OCR processed, 12/14 fields extracted
   [View original] [View OCR overlay] [Download]

── CONVERSATION ────────────────────────────────
[Full transcript — 18 messages, 4m 32s]
```

### 12.5 Pipeline View — Processing Transparency

For each session, the admin can trace every processing step:

```
PIPELINE — Session #142
━━━━━━━━━━━━━━━━━━━━━━━

1. [14:23:01] MESSAGE_RECEIVED
   User: "Vorrei un prestito personale di 10.000 euro"
   → LLM input: [system prompt: NEEDS_ASSESSMENT] + user message
   → LLM output: {"action": "collect", "product_interest": "prestito_personale", ...}
   → LLM latency: 1.2s, tokens: 85 in / 62 out

2. [14:23:15] STATE_TRANSITION
   NEEDS_ASSESSMENT → EMPLOYMENT_TYPE

3. [14:23:45] MESSAGE_RECEIVED
   User: "Dipendente"
   → LLM: detected employment_type = dipendente
   → STATE_TRANSITION → EMPLOYER_CLASS_DIP

4. [14:24:10] MESSAGE_RECEIVED
   User: "Azienda privata"
   → employer_category = privato
   → STATE_TRANSITION → TRACK_CHOICE_EMP

5. [14:24:30] DOCUMENT_RECEIVED
   Type: image/jpeg, 1.4 MB
   → Preprocessing: resized 3024×4032 → 1440×1920 (0.3s)

6. [14:24:32] DOCUMENT_CLASSIFICATION
   Model: qwen2.5-vl-7b-q4
   → Result: "busta_paga" (confidence 0.97)
   → Latency: 2.1s

7. [14:24:35] OCR_EXTRACTION
   Model: qwen2.5-vl-7b-q4
   → Prompt: [payslip extraction prompt]
   → Result: {employee_name: "Maria Rossi", net_salary: 1750, ...}
   → Confidence: {employee_name: 0.98, net_salary: 0.97, hiring_date: 0.82}
   → Latency: 8.4s
   → ⚠️ hiring_date confidence below threshold (0.82 < 0.85)

8. [14:24:36] CF_DECODE
   Input: RSSMRA85H52F205R
   → Checksum: VALID
   → Birthdate: 1985-06-12, Age: 40, Gender: F, Birthplace: F205 (Milano)
   → Latency: <1ms

9. [14:24:37] CdQ_DEDUCTION_SCAN
   → No CdQ/Delega deductions detected on payslip

10. [14:25:10] USER_CONFIRMATION
    User confirmed all OCR data
    → Source upgraded: ocr → ocr_confirmed

11. [14:26:00] LIABILITIES_COLLECTED
    2 liabilities declared (manual)
    → Total monthly: €400

12. [14:26:01] DTI_CALCULATION
    Monthly income: €1,750
    Monthly obligations: €400
    DTI: 22.9%

13. [14:26:01] CDQ_CALCULATION
    Max rata: €350
    Available: €350
    Delega available: €350

14. [14:26:02] PRODUCT_MATCHING
    Rules evaluated: 47
    Matches: 5 products
    Primary: CdQ Dipendente Azienda Privata

15. [14:27:33] APPOINTMENT_BOOKED
    Operator: Mario Bianchi
    Time: 2026-02-14 15:00
    Dossier generated and sent
```

### 12.6 Admin Technical Architecture

```python
# Admin bot runs as a separate Telegram bot instance
# connected to the same database and Redis

class AdminBot:
    def __init__(self, token: str, db: AsyncSession, redis: Redis):
        self.bot = TelegramBot(token)
        self.db = db
        self.redis = redis
        self.subscribers = {}  # session_id → set of admin telegram_ids

    async def on_system_event(self, event: SystemEvent):
        """Called by the main system on every event."""
        # 1. Log to database (audit trail)
        await self.db.execute(insert(AuditLog).values(
            event_type=event.type,
            session_id=event.session_id,
            data=event.data,
            timestamp=event.timestamp
        ))

        # 2. Push to subscribed admins (/live command)
        if event.session_id in self.subscribers:
            for admin_id in self.subscribers[event.session_id]:
                await self.bot.send_message(admin_id, format_event(event))

        # 3. Check alert rules
        alerts = check_alert_rules(event)
        for alert in alerts:
            for admin_id in get_admin_ids():
                await self.bot.send_message(admin_id, format_alert(alert))

# Web dashboard — lightweight FastAPI + Jinja2 + HTMX
from fastapi import FastAPI, Depends
from fastapi.templating import Jinja2Templates

admin_app = FastAPI(prefix="/admin")
templates = Jinja2Templates(directory="templates/admin")

@admin_app.get("/")
async def dashboard(request: Request, user=Depends(verify_admin)):
    active = await get_active_sessions()
    today_stats = await get_today_stats()
    alerts = await get_active_alerts()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "active": active,
        "stats": today_stats, "alerts": alerts
    })

@admin_app.get("/session/{session_id}")
async def session_detail(session_id: int, request: Request, user=Depends(verify_admin)):
    session = await get_session_full(session_id)
    # Log admin access (audit)
    await log_admin_access(user.id, "view_session", session_id)
    return templates.TemplateResponse("session_detail.html", {
        "request": request, "session": session
    })
```

### 12.7 Event System

Every action in the system emits an event that feeds both the admin interface and the audit log:

| Event Type | Data Included | Triggers Alert? |
|---|---|---|
| `session.started` | user_id, channel, timestamp | No (high volume) |
| `session.state_changed` | from_state, to_state | Only if → HUMAN_ESCALATION |
| `message.received` | content (redacted in logs if sensitive) | No |
| `message.sent` | content | No |
| `llm.request` | prompt hash, model, tokens_in | No |
| `llm.response` | response hash, tokens_out, latency_ms | If latency > 30s |
| `document.received` | doc_type, file_size | No |
| `document.classified` | predicted_type, confidence | If confidence < 0.80 |
| `ocr.completed` | fields_extracted, confidence_map | If any field < 0.70 |
| `cf.decoded` | age, gender (no full CF in event) | If checksum fails |
| `deduction.detected` | type, amount | Always (important info) |
| `liability.collected` | type, monthly_installment | No |
| `dti.calculated` | current_dti, projected_dti | If > 40% |
| `cdq.calculated` | available_cdq, available_delega | If available ≤ 0 |
| `products.matched` | count, product_names | Always |
| `eligibility.decided` | outcome | Always |
| `appointment.booked` | datetime, operator | Always |
| `consent.given` | consent_types | No |
| `data_deletion.requested` | user_id | Always (critical) |
| `error.occurred` | error_type, stack_trace | Always |

---

## 13. Scheduling & Human Handoff

### 13.1 Flow

1. Present 3–5 slots from Cal.com/Calendly
2. User selects
3. Book appointment → admin notified via Telegram
4. Confirmation with date, time, Primo Network contact (800.99.00.90)
5. Reminders: 24h + 1h before
6. Option: "Primo Network offre anche consulenza a domicilio."

### 13.2 Lead Dossier

Pre-filled data mapped to Primo Network's quotation forms. Admin can view via `/dossier <id>` or web dashboard.

**Structure:** Anagrafica → Situazione lavorativa → Nucleo familiare → Impegni finanziari → Calcoli (DTI, CdQ) → Prodotti compatibili → Pre-filled quotation data → Documenti allegati → Transcript.

### 13.3 Escalation Paths

- User requests human operator
- Conversation loops 3+ turns
- OCR fails after 2 retries
- Mixed income (employed + P.IVA)
- Complex liabilities (> 4 active)
- Financial distress indicators
- Legal questions
- CIG/cassa integrazione
- Admin intervenes via `/intervene <id>`

---

## 14. Regulatory Compliance & Legal Framework

This section documents the regulatory landscape and the system's compliance posture. **Full legal compliance assessment should be conducted with qualified legal counsel before production launch.** The architecture has been designed to enable compliance; the specific implementation details (privacy policy text, DPIA documents, etc.) are a dedicated workstream.

### 14.1 Applicable Regulations

| Regulation | Full Reference | Applicability | Impact |
|---|---|---|---|
| **EU AI Act** | Reg. (EU) 2024/1689 | BrokerBot is an AI system interacting with natural persons and potentially involved in creditworthiness assessment | High — possible high-risk classification |
| **GDPR** | Reg. (EU) 2016/679 | Processes personal data of EU residents | High — core compliance requirement |
| **Italian Privacy Code** | D.Lgs. 196/2003, updated by D.Lgs. 101/2018 | Italian implementation of GDPR + additional national rules | High |
| **ePrivacy Directive** | Directive 2002/58/EC | Electronic communications, messaging | Medium |
| **NIS2 Directive** | Directive (EU) 2022/2555 | Cybersecurity requirements — may apply if system handles financial data at scale | Medium — assess threshold |
| **D.Lgs. 141/2010** | Credit intermediation law | Regulates mediatori creditizi — Primo Network must ensure bot activity is compliant with intermediation rules | High |
| **DPR 180/1950** | CdQ regulation | Governs cessione del quinto products | Medium — product rules already encoded |
| **Banca d'Italia Transparency** | Provvedimento 29/7/2009 and updates | Transparency requirements for credit intermediaries | Medium |
| **Consumer Credit Directive** | Directive 2008/48/EC (under revision as 2023/2225) | Consumer credit advertising and information | Medium |
| **Italian Cybersecurity Perimeter** | D.L. 105/2019, D.P.C.M. 81/2021 | National cybersecurity framework — assess if applicable | Low–Medium |
| **ACN Guidelines** | Agenzia per la Cybersicurezza Nazionale | Italian cybersecurity agency recommendations | Advisory |

### 14.2 EU AI Act — Classification & Obligations

**Risk classification assessment:**

BrokerBot assists in lead qualification for credit products. Under the AI Act:

- **Art. 6(2) + Annex III, point 5(b):** AI systems intended to be used to *evaluate the creditworthiness of natural persons* are classified as **high-risk**.
- **However:** BrokerBot does not make credit decisions. It qualifies leads and collects data; the actual credit decision is made by the lending institution after human review by a Primo Network consultant.
- **Likely classification: Could argue for non-high-risk** if positioned as a data collection and pre-screening tool with no autonomous credit decisions. But this must be confirmed by legal counsel.

**Regardless of classification, the following are implemented:**

| AI Act Requirement | Article | Implementation |
|---|---|---|
| **Transparency** — inform users they interact with AI | Art. 50(1) | CONSENT state: explicit AI disclosure before any data collection |
| **Transparency** — mark AI-generated content | Art. 50(3) | All bot messages clearly from "Assistente ameconviene.it" |
| **Human oversight** | Art. 14 (if high-risk) | Final decisions always by human consultant; admin can intervene at any point |
| **Risk management** | Art. 9 (if high-risk) | Risk register maintained; mitigations documented in this PRD |
| **Data governance** | Art. 10 (if high-risk) | Data quality controls, confidence scoring, source tracking |
| **Record-keeping** | Art. 12 (if high-risk) | Full audit log of every processing step (Section 12) |
| **Technical documentation** | Art. 11 (if high-risk) | This PRD + system documentation |
| **Accuracy, robustness, cybersecurity** | Art. 15 (if high-risk) | OCR confidence thresholds, user confirmation, fallback to manual |

**Action item:** Engage legal counsel to produce formal AI Act classification opinion before production launch. Prepare FRIA (Fundamental Rights Impact Assessment) if classified as high-risk.

### 14.3 GDPR Compliance

| GDPR Requirement | Article | Implementation |
|---|---|---|
| **Lawful basis** | Art. 6 | Consent (Art. 6(1)(a)) for data processing; legitimate interest for system security |
| **Special categories** | Art. 9 | Financial data may qualify as special category in some interpretations — explicit consent collected |
| **Transparency / information** | Art. 13–14 | CONSENT state provides: identity of controller (Primo Network), purposes, data categories, retention, rights. Link to full privacy policy. |
| **Consent** | Art. 7 | Unambiguous, freely given, specific, informed. Separate consents for: contractual processing, sensitive data, Primo Network marketing, third-party marketing. |
| **Right of access** | Art. 15 | User can request all collected data via `/i_miei_dati` command or contact Primo Network |
| **Right to rectification** | Art. 16 | User can correct data during conversation; admin can correct post-conversation |
| **Right to erasure** | Art. 17 | `/elimina_dati` command triggers: delete all personal data, documents, conversation. Admin notified. Confirmation sent. |
| **Right to data portability** | Art. 20 | Export data in JSON format via admin panel or user request |
| **Data minimization** | Art. 5(1)(c) | Only fields required for quotation are collected; no unnecessary data |
| **Storage limitation** | Art. 5(1)(e) | Raw documents: 30 days. Extracted data: 12 months. Anonymized analytics: indefinite. |
| **Integrity & confidentiality** | Art. 5(1)(f) | AES-256 at rest, TLS 1.3 in transit, access controls |
| **DPO** | Art. 37–39 | Primo Network's DPO (if appointed) or designated privacy contact |
| **DPIA** | Art. 35 | Required before production — processing of financial data at scale likely triggers DPIA obligation |
| **Data breach notification** | Art. 33–34 | Automated breach detection; notify Garante (Italian DPA) within 72 hours; notify affected users if high risk |
| **Processor agreements** | Art. 28 | If Giuseppe Giordano / ameconviene.it acts as data processor for Primo Network → formal DPA (Data Processing Agreement) required |
| **International transfers** | Art. 44–49 | No transfers outside EU — all processing local, EU data centers only |

**Key GDPR architecture decisions:**
- All LLM inference is local → no data sent to OpenAI, Google, etc.
- No cloud storage → documents stored on-premise, encrypted
- CF and financial data encrypted at rest with field-level encryption
- Audit log tracks every data access (who, when, what)
- Automated data retention enforcement (cron job deletes expired data)

### 14.4 Italian-Specific Requirements

| Requirement | Reference | Implementation |
|---|---|---|
| **Garante Privacy guidelines on AI** | Various provvedimenti | AI disclosure, no fully automated decisions on financial matters |
| **D.Lgs. 141/2010 — Credit intermediation** | Art. 128-quater and ff. | Bot is a tool of the mediatore creditizio (Primo Network); bot does not itself act as intermediary. All recommendations are preliminary and subject to human review. |
| **Banca d'Italia transparency** | Provvedimento 29/7/2009 | Primo Network's legal information (OAM, IVASS, Cap. Soc.) displayed in bot welcome. Links to trasparenza documents. |
| **OAM obligations** | Various | Bot activity falls under Primo Network's OAM M94 registration. Ensure OAM is informed of AI-assisted operations if required. |
| **Codice del Consumo** | D.Lgs. 206/2005 | Consumer protection: clear product information, no misleading claims, right of withdrawal information |
| **Anti-money laundering** | D.Lgs. 231/2007 | Know-your-customer (KYC): CF validation, identity verification. Full KYC remains with Primo Network operator at human handoff. |

### 14.5 NIS2 Considerations

The NIS2 Directive (transposed in Italy by D.Lgs. 138/2024) applies to essential and important entities in certain sectors. Financial services entities above certain thresholds are in scope.

**Assessment:** Primo Network as a mediatore creditizio may or may not be in scope (depends on size and revenue thresholds). Regardless, implementing NIS2-aligned cybersecurity practices is prudent:

| NIS2 Measure | Implementation |
|---|---|
| Risk management | Documented risk register (Section 19) |
| Incident handling | Breach detection, admin alerts, notification procedures |
| Business continuity | Backup strategy, failover procedures |
| Supply chain security | All LLMs open-source, locally hosted; no third-party SaaS dependencies for core processing |
| Encryption | AES-256 at rest, TLS 1.3 in transit |
| Access control | Role-based access, admin audit log |
| Vulnerability management | Regular dependency updates, security scanning |

### 14.6 Compliance Roadmap

| Phase | Compliance Activity | When |
|---|---|---|
| **Pre-MVP** | Formal GDPR DPA between Giuseppe Giordano / ameconviene.it and Primo Network Srl | Before development |
| **Pre-MVP** | Draft privacy policy and informativa per il trattamento dei dati | Before development |
| **Phase 1** | AI Act transparency implementation (CONSENT state, disclosures) | Built into MVP |
| **Phase 1** | Audit logging and admin interface | Built into MVP |
| **Phase 1** | Data encryption and access controls | Built into MVP |
| **Phase 1** | Consent management and `/elimina_dati` | Built into MVP |
| **Pre-Production** | DPIA (Data Protection Impact Assessment) | Before public launch |
| **Pre-Production** | AI Act classification opinion from legal counsel | Before public launch |
| **Pre-Production** | FRIA (Fundamental Rights Impact Assessment) if high-risk classification | Before public launch |
| **Pre-Production** | Review by Primo Network's compliance/legal team | Before public launch |
| **Pre-Production** | OAM notification if required | Before public launch |
| **Phase 2** | Penetration testing | Within 4 weeks of production |
| **Phase 2** | NIS2 gap assessment (if applicable) | Within 8 weeks of production |
| **Ongoing** | Quarterly compliance review | Every 3 months |
| **Ongoing** | Annual DPIA update | Every 12 months |

### 14.7 Bot Disclaimers

The following disclaimers are embedded in the conversation at appropriate points:

**Welcome/Consent:**
"Sta parlando con un assistente basato su intelligenza artificiale. Le informazioni fornite hanno carattere puramente indicativo e non costituiscono consulenza finanziaria. Le decisioni finali sono sempre prese da un consulente qualificato di Primo Network Srl. Servizio offerto da Primo Network Srl, mediatore creditizio iscritto all'OAM al n. M94."

**Eligibility result:**
"Questa è una verifica preliminare basata sui dati forniti. L'idoneità definitiva sarà confermata dal consulente Primo Network dopo un'analisi approfondita."

**Product presentation:**
"I tassi e le condizioni indicate sono a titolo orientativo e possono variare. Per le condizioni contrattuali definitive si rimanda alla documentazione fornita dagli istituti eroganti."

---

## 15. Security & Privacy — Technical Implementation

### 15.1 Data Encryption

| Data State | Method | Details |
|---|---|---|
| At rest — database | AES-256-GCM | Field-level encryption for CF, financial data, P.IVA |
| At rest — documents | AES-256-GCM | Stored in encrypted file system, separate from DB |
| In transit — user ↔ bot | TLS 1.3 | Via WhatsApp/Telegram (E2E encrypted by platform) |
| In transit — internal | TLS 1.3 | Between services (FastAPI ↔ PostgreSQL ↔ Redis) |
| In memory — LLM | Ephemeral | No persistence; model context cleared after each request |
| Backups | AES-256 | Encrypted backups to separate encrypted volume |

### 15.2 Access Control

| Resource | Admin (Giuseppe) | Operator | User |
|---|---|---|---|
| All sessions | ✅ | ❌ (only assigned) | ❌ (only own) |
| Raw LLM logs | ✅ | ❌ | ❌ |
| Documents | ✅ | ✅ (assigned only) | ❌ (uploaded only) |
| System config | ✅ | ❌ | ❌ |
| Eligibility rules | ✅ (read/write) | ✅ (read) | ❌ |
| Audit log | ✅ | ❌ | ❌ |
| Analytics | ✅ | ✅ (aggregated) | ❌ |
| Data deletion | ✅ | ❌ | ✅ (own data) |

### 15.3 Data Retention

| Data Type | Retention | Deletion Method |
|---|---|---|
| Raw documents (images, PDFs) | 30 days | Secure wipe (overwrite + delete) |
| Conversation transcripts | 12 months | Database hard delete |
| Extracted personal data | 12 months | Database hard delete |
| Aggregated analytics | Indefinite | Fully anonymized, no personal data |
| Audit logs | 24 months (regulatory requirement) | Archived, then deleted |
| User consent records | Duration of relationship + 5 years | Regulatory retention |

### 15.4 `/elimina_dati` — Right to Erasure Flow

```
1. User sends /elimina_dati
2. Bot confirms: "Questa azione eliminerà tutti i suoi dati personali
   dal nostro sistema. Vuole procedere?"
3. User confirms
4. System:
   a. Deletes all documents
   b. Deletes all extracted data
   c. Anonymizes conversation (replace PII with [REDACTED])
   d. Deletes user record
   e. Logs deletion event in audit trail (anonymized)
   f. Notifies admin via Telegram
   g. Sends confirmation to user
5. If appointment exists: cancels and notifies operator
```

### 15.5 Rate Limiting

- Max 60 messages per session per hour
- Max 8 document uploads per session
- Max 3 sessions per phone number per day
- Flood detection: block > 10 messages/minute
- Admin notified on rate limit triggers

---

## 16. Technology Stack & Infrastructure

| Component | Technology |
|---|---|
| Runtime | Python 3.12+ |
| API Framework | FastAPI |
| LLM Runtime | Ollama |
| Conversation LLM | Qwen3 8B (Q4_K_M) |
| Vision LLM | Qwen2.5-VL 7B (Q4_K_M) |
| CF Decoder | Pure Python |
| Calculators | Pure Python (CdQ, DTI) |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis |
| Task Queue | Celery / ARQ |
| WhatsApp | WhatsApp Business API |
| Telegram (User) | python-telegram-bot |
| **Telegram (Admin)** | **python-telegram-bot (separate bot)** |
| **Web Admin** | **FastAPI + Jinja2 + HTMX** |
| Scheduling | Cal.com / Calendly |
| Containers | Docker + Compose |
| Monitoring | Prometheus + Grafana |
| Logging | Structured (JSON) → PostgreSQL + stdout |
| Secrets | HashiCorp Vault or SOPS (encrypted env files) |

### 16.1 Hardware

- **MVP:** MacBook Pro M2 16GB
- **Production:** Mac Mini M4 32GB or VPS RTX 3060 12GB
- **GDPR:** EU-only data centers (Hetzner/OVH)

---

## 17. Data Model

| Entity | Key Fields |
|---|---|
| `User` | id, phone, channel, email, first_seen, last_active, consent_status (JSONB), anonymized |
| `Session` | id, user_id, current_state, employment_type, employer_category, pension_source, track_type, income_doc_type, outcome, started_at, completed_at |
| `Message` | id, session_id, role, content, media_url, timestamp |
| `Document` | id, session_id, doc_type, file_path (encrypted), ocr_result (JSONB), confidence_scores, expires_at |
| `ExtractedData` | id, session_id, field_name, value (encrypted for PII), source, confidence |
| `HouseholdData` | id, session_id, nucleo_familiare, percettori_reddito, provincia_residenza, provincia_immobile |
| `Liability` | id, session_id, type, monthly_installment, remaining_months, total_months, paid_months, residual_amount, lender, detected_from, supporting_doc_id, renewable |
| `DTICalculation` | id, session_id, monthly_income, total_obligations, proposed_installment, current_dti, projected_dti |
| `CdQCalculation` | id, session_id, net_income, max_cdq_rata, existing_cdq, available_cdq, max_delega_rata, existing_delega, available_delega |
| `ProductMatch` | id, session_id, product_name, sub_type, eligible, conditions (JSONB), estimated_terms (JSONB), rank |
| `QuotationData` | id, session_id, form_type, form_fields (JSONB) |
| `Appointment` | id, session_id, operator_id, scheduled_at, status, cal_event_id |
| `Operator` | id, name, email, calendar_id, specializations |
| **`AuditLog`** | **id, timestamp, event_type, session_id, actor_id, actor_role, data (JSONB)** |
| **`ConsentRecord`** | **id, user_id, consent_type, granted, timestamp, ip_hash, method** |
| **`DataDeletionRequest`** | **id, user_id, requested_at, completed_at, status, admin_notified** |
| **`AdminAccess`** | **id, admin_id, action, target_entity, target_id, timestamp** |

### 17.1 Source Tracking

| Source | Meaning |
|---|---|
| `ocr` | VLM extraction |
| `ocr_confirmed` | OCR + user confirmed |
| `ocr_detected` | Auto-detected (e.g., CdQ deduction) |
| `cf_decode` | From codice fiscale |
| `computed` | Calculated (DTI, CdQ, forfettario) |
| `manual` | User-provided via Q&A |
| `api` | External API |
| `self_declared` | User stated, unverified |

---

## 18. Development Roadmap

### Phase 1: MVP (Weeks 1–10)

**Deliverables:** Fully functional on Telegram + WhatsApp with admin visibility from day one.

| Week | Work |
|---|---|
| 1–2 | Project setup, Ollama, FSM engine, CONSENT + WELCOME states, ameconviene.it branding, **admin Telegram bot (core commands)**, audit logging |
| 3–4 | Dipendente path: payslip OCR, employer classification, CF decoder, CdQ calculator, user confirmation |
| 4–5 | **Admin web dashboard** (sessions list, session detail, pipeline view) |
| 5–6 | P.IVA path: dichiarazione OCR, forfettario logic, manual Q&A |
| 6–7 | Pensionato path: cedolino OCR, pension classification, CdQ detection, TFS check |
| 7–8 | Disoccupato path, household data, liabilities module (collection, DTI, CdQ renewal, optional docs) |
| 8–9 | Product matching engine, dossier generation, pre-filled quotation data |
| 9–10 | Scheduling integration, **admin alerts**, consent management, `/elimina_dati`, WhatsApp integration, end-to-end testing |

**Phase 1 admin deliverables:**
- Telegram admin bot with all commands from Section 12.2
- Web dashboard with session list, session detail, pipeline view, health page
- Push alerts for all critical events
- Audit logging for every system event
- GDPR consent tracking and data deletion workflow

### Phase 2: Production Hardening (Weeks 11–16)

- Production infrastructure (dedicated server, monitoring, backups)
- Admin dashboard enhancements: analytics page, GDPR dashboard, rules editor
- External API integration (CRIF, Registro Imprese)
- Proper admin authentication (JWT + 2FA)
- Operator accounts with role-based access
- DPIA completion
- AI Act classification opinion from legal counsel
- Penetration testing
- Testing with real documents across all types

### Phase 3: Scale (Weeks 17–24)

- Embeddable web widget for ameconviene.it / pnit.it
- Mobile app with document scanner
- Advanced analytics: funnel by product × employment type, DTI distribution, geographic breakdown
- CdQ rinnovo automated workflow
- Multi-language support
- Fine-tuned OCR models on Italian document datasets
- Mixed income support (employed + P.IVA)
- Direct API submission to Primo Network quotation system
- NIS2 gap assessment (if applicable)

---

## 19. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| AI Act high-risk classification | High | Medium | Architecture supports compliance; legal opinion before launch; human-in-the-loop by design |
| GDPR breach | Critical | Low | Local processing, encryption, access controls, audit log, DPIA |
| OCR misreads salary/pension | High | Medium | Confidence scoring + user confirmation + admin visibility |
| Wrong employer classification | Medium | Medium | LLM + user confirmation; admin can correct |
| CdQ rata miscalculation | High | Low | Pure Python calculator, unit tested, user confirms net income |
| User under-reports liabilities | High | Medium | Cross-check OCR-detected deductions vs declared |
| DTI calculation error | High | Low | Unit tested, all inputs confirmed, operator re-checks |
| Primo Network product changes | Medium | Medium | Excel-based rules, admin can update without code |
| Tax return too complex for OCR | High | High | Focus Quadro RN; fallback to manual; escalate |
| Model too slow on 16GB | Medium | High | Sequential loading; production 32GB+ |
| Regulatory non-compliance | Critical | Medium | Compliance roadmap (Section 14.6); legal counsel; phased approach |
| Brand confusion (ameconviene.it vs Primo Network) | Medium | Low | Clear disclosures; Primo Network identified as legal entity in all regulatory contexts |
| Admin bot compromised | Critical | Low | Separate bot token, IP-restricted where possible, admin actions logged |
| Data processor liability | High | Medium | Formal DPA between Giuseppe Giordano and Primo Network before development |

---

## 20. Success Metrics & KPIs

| KPI | Target (6 months) |
|---|---|
| Lead qualification rate | > 80% |
| Data completeness for quotation | > 90% of form fields |
| Fast track adoption (dipendenti) | > 65% |
| Fast track adoption (pensionati) | > 55% |
| Fast track adoption (P.IVA) | > 45% |
| OCR accuracy (payslip) | > 95% |
| OCR accuracy (cedolino) | > 93% |
| OCR accuracy (tax return) | > 90% |
| CdQ rata accuracy | > 99% |
| DTI accuracy | > 98% |
| CdQ detection from docs | > 90% |
| Call booking rate (eligible) | > 70% |
| Time to qualification (fast) | < 5 min |
| Time to qualification (manual) | < 10 min |
| Admin alert latency | < 60 seconds |
| GDPR deletion compliance | < 24 hours |
| System uptime | > 99.5% |
| Operator time saved | > 15h/week |
| Cost per qualified lead | < €2 |

---

## 21. Appendix

### 21.1 Sample Conversation — Full ameconviene.it Branding with Consent

| Role | Message |
|---|---|
| **Bot** | Benvenuto/a su **ameconviene.it**! Sono l'assistente digitale per il confronto dei migliori prodotti finanziari, un servizio offerto da Primo Network Srl (mediatore creditizio OAM M94). |
| **Bot** | 🤖 Sta parlando con un'intelligenza artificiale. Le valutazioni finali sono sempre confermate da un consulente qualificato. 🔒 I suoi dati sono trattati in modo sicuro e non vengono inviati a servizi esterni. Per procedere ho bisogno del suo consenso al trattamento dei dati per finalità contrattuali e dati sensibili. Acconsente? Può revocare in qualsiasi momento con /elimina_dati. |
| **User** | Sì, acconsento |
| **Bot** | Grazie! Posso aiutarla con cessione del quinto, prestiti personali, mutui, consolidamento debiti e altro. Per quale esigenza posso assisterla? |
| **User** | Vorrei una cessione del quinto |
| **Bot** | Perfetto! È un lavoratore dipendente o un pensionato? |
| **User** | Dipendente pubblico |
| **Bot** | Ottimo, il settore pubblico offre le condizioni migliori per la cessione del quinto. Può scegliere: 🚀 **Veloce:** mi invii la busta paga e verifico in pochi secondi. 💬 **Manuale:** le faccio qualche domanda. |
| **User** | *[sends payslip]* |
| **Bot** | Sto analizzando... ✅ Nome: Anna Verdi — CF: VRDNNA80A45L219P — Età: 46 anni — Ente: ASL TO1 — Contratto: Tempo indeterminato — Assunta dal: 01/09/2005 — Netto: €1.920 — Nessuna trattenuta CdQ rilevata. Corretto? |
| **User** | Sì |
| **Bot** | Ha altri finanziamenti in corso? |
| **User** | Un prestito auto da 180 euro al mese, mancano 12 rate |
| **Bot** | Capito. Riepilogo: **Netto:** €1.920 — **CdQ max rata:** €384 — **Prestito auto:** €180/mese (12 rate). **DTI attuale:** 9,4%. Con una cessione del quinto a 120 mesi e rata massima di €384, potrebbe ottenere una liquidità netta stimata di €32.000–€38.000 con i migliori tassi confrontati da Primo Network. *Nota: questa è una stima preliminare. Le condizioni definitive saranno confermate dal consulente.* Vuole fissare una chiamata gratuita? |

### 21.2 Admin Interaction Example

```
[Telegram Admin Bot — Giuseppe Giordano]

Giuseppe: /active
Bot:      📊 3 sessioni attive:
          #201 — Anna Verdi (dipendente pubblico, PRODUCT_MATCHING) ⏱️ 3m
          #202 — Marco B. (pensionato INPS, LIABILITIES) ⏱️ 5m
          #203 — Sara R. (P.IVA, DOC_PROCESSING) ⏱️ 1m

Giuseppe: /live 201
Bot:      🔴 LIVE — Sessione #201 (Anna Verdi)
          Ogni evento verrà inviato in tempo reale.

Bot:      [14:26:02] PRODUCT_MATCHING completato
          → 5 prodotti compatibili
          → Primario: CdQ Dipendente Pubblico (rata max €384)
          → DTI: 9.4% ✅

Bot:      [14:26:45] Utente ha scelto di fissare una chiamata

Bot:      [14:27:10] 📅 APPUNTAMENTO CONFERMATO
          Anna Verdi — Domani 15:00 — Operatore: Mario Rossi
          → Dossier generato

Giuseppe: /dossier 201
Bot:      📋 DOSSIER #201 — Anna Verdi
          [generates and sends full dossier as formatted message]

Giuseppe: /today
Bot:      📊 Riepilogo oggi (13 Feb 2026):
          Sessioni avviate: 8
          Completate: 6 (75%)
          Idonei: 4
          Chiamate prenotate: 3
          Prodotto più richiesto: CdQ Stipendio (50%)
          DTI medio: 24.3%
          Tempo medio qualifica: 4m 48s
```

### 21.3 Primo Network Product-Form Mapping

| Primo Network Form | URL | BrokerBot Pre-fills |
|---|---|---|
| CQS/Delega Calculator | /richiesta-calcolo-preventivo-cqs.html | data_nascita, prodotto, rata, durata, data_assunzione, nome, cognome, email, cellulare |
| Mutuo Calculator | /richiesta-calcolo-preventivo-mutuo.html | prodotto, durata, cadenza, importo, prima_casa, prezzo_acquisto, provincia_immobile, reddito_netto, rata_debiti, nucleo_familiare, percettori_reddito, data_nascita, data_assunzione, nome, cognome, email, cellulare |
| Generic Quote | /richiesta-preventivo.html | importo, prodotto, provincia_residenza, data_nascita, nome, cognome, email, cellulare |

### 21.4 Glossary

| Term | Definition |
|---|---|
| ameconviene.it | Consumer-facing brand for the BrokerBot chatbot |
| Primo Network | Credit brokerage firm (mediatore creditizio), OAM M94, Turin |
| OAM | Organismo degli Agenti e dei Mediatori |
| IVASS | Insurance supervisory authority |
| AI Act | EU Reg. 2024/1689 on Artificial Intelligence |
| GDPR | EU Reg. 2016/679 on data protection |
| NIS2 | EU Directive 2022/2555 on cybersecurity |
| DPIA | Data Protection Impact Assessment |
| FRIA | Fundamental Rights Impact Assessment (AI Act) |
| DPA | Data Processing Agreement (GDPR Art. 28) |
| Garante | Italian Data Protection Authority |
| ACN | Agenzia per la Cybersicurezza Nazionale |
| CdQ | Cessione del quinto — salary/pension-backed loan (max 1/5 net) |
| Delega | Delegazione di pagamento — additional 1/5 alongside CdQ |
| DPR 180/1950 | Italian law regulating CdQ and Delega |
| D.Lgs. 141/2010 | Italian credit intermediation law |
| Rinnovo | CdQ renewal — requires ≥ 40% paid |
| Prefinanziamento | Quick advance (up to 50%) |
| DTI | Debt-to-income ratio |
| TFR / TFS | Severance pay (private / public) |
| INPDAP | Former public pension institute (now INPS) |
| Consap | State guarantee fund for mortgages |
| CCNL | National collective labor agreement |
| NASpI | Unemployment benefit |
| ATECO | Business activity code |
| Regime forfettario | Flat-rate tax scheme |
| CRIF | Italian credit bureau |
| TAEG | APR equivalent |
| IRS / Euribor | Fixed / variable mortgage reference rates |
| LTV | Loan-to-Value ratio |

---

*End of Document — BrokerBot PRD v1.5 for ameconviene.it / Primo Network Srl*
*Author: Giuseppe Giordano*
