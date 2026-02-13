# Agents — BrokerBot

This project uses specialized agents for Claude Code. Each agent has deep domain knowledge of a specific subsystem. Invoke the right agent when working on that part of the codebase.

## Agent List

| Agent | File | Domain | When to Use |
|---|---|---|---|
| **foundation** | `foundation.md` | DB models, config, event system, LLM client | Setting up core infrastructure, models, migrations |
| **conversation** | `conversation.md` | FSM, state handlers, LLM prompts, Italian UX | Building conversation flow, writing prompts, handling user messages |
| **ocr** | `ocr.md` | Document processing, image preprocessing, extraction, validation | Working on payslip/cedolino/tax return OCR |
| **calculators** | `calculators.md` | CF decoder, CdQ, DTI, income normalization, eligibility | Financial calculations, product matching, business rules |
| **admin** | `admin.md` | Telegram admin bot, web dashboard, alerts, audit, GDPR | Admin interface, monitoring, event system |
| **channels** | `channels.md` | Telegram user bot, WhatsApp integration, message normalization | Messaging integration, webhook handling |
| **compliance** | `compliance.md` | GDPR, AI Act, consent, encryption, audit logging, data retention | Security features, consent management, erasure, regulatory |

## How to Use

When starting work on a subsystem, read the corresponding agent file first. It contains:
- **Context:** What this subsystem does and why
- **Key decisions:** Architecture choices already made
- **Dependencies:** What this subsystem needs from others
- **Implementation notes:** Specific patterns, gotchas, Italian-specific details
- **Task checklist:** Ordered list of what to build

## Build Order

```
Week 1-2:  foundation → admin (core event system + telegram bot)
Week 3-4:  calculators → conversation (dipendente path) → ocr (busta paga)
Week 5-6:  conversation (P.IVA path) → ocr (dichiarazione)
Week 6-7:  conversation (pensionato) → ocr (cedolino) → calculators (TFS)
Week 7-8:  conversation (disoccupato + liabilities) → admin (web dashboard)
Week 8-9:  eligibility engine → dossier builder → channels (WhatsApp)
Week 9-10: scheduling → integration testing → admin alerts
```
