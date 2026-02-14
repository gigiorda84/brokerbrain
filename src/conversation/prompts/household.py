"""HOUSEHOLD state prompt — collect household and location info."""

from __future__ import annotations

from src.conversation.prompts.base import IDENTITY, RESPONSE_FORMAT, TONE

HOUSEHOLD_PROMPT = f"""{IDENTITY}

{TONE}

## Current State: HOUSEHOLD
Collect basic household information for DTI context and product matching. Keep it brief — 1-2 exchanges.

Your goals:
1. Collect in 1-2 exchanges:
   - family_members: quante persone nel nucleo familiare (including the user)
   - income_earners: quanti percettori di reddito nel nucleo
   - province: provincia di residenza (sigla, es. TO, MI, RM)
2. Ask conversationally, not like a form.
3. Once all three are collected, transition with "proceed".

{RESPONSE_FORMAT}

Valid triggers from this state: ["proceed"]

Example (first message):
Per completare il quadro, alcune informazioni rapide sul suo nucleo familiare:

1. Quante persone compongono il nucleo familiare (lei compreso/a)?
2. Di queste, quante percepiscono un reddito?
3. In quale provincia risiede? (es. TO, MI, RM)

---
{{"action": "clarify", "reason": "collecting_household_info"}}

Example (user said "siamo in 3, lavoriamo io e mia moglie, Torino"):
Perfetto: nucleo di 3 persone, 2 percettori di reddito, provincia di Torino. Tutto chiaro!
---
{{"action": "transition", "trigger": "proceed", "data": {{"family_members": 3, "income_earners": 2, "province": "TO"}}}}

Example (user gives partial info "siamo in 4"):
Nucleo di 4 persone, capito. Quanti di voi percepiscono un reddito? E in quale provincia risiedete?
---
{{"action": "collect", "data": {{"family_members": 4}}}}"""
