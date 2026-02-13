"""EMPLOYMENT_TYPE state prompt — classify the user's employment."""

from __future__ import annotations

from src.conversation.prompts.base import IDENTITY, RESPONSE_FORMAT, TONE

EMPLOYMENT_TYPE_PROMPT = f"""{IDENTITY}

{TONE}

## Current State: EMPLOYMENT_TYPE
Determine the user's employment type. This is critical for product eligibility.

Your goals:
1. Ask about their current employment status.
2. Classify into one of: dipendente, partita_iva, pensionato, disoccupato, mixed.
3. "Dipendente" includes both public and private sector employees.
4. "Partita IVA" includes freelancers and self-employed.
5. "Pensionato" includes all retirees.
6. "Disoccupato" includes unemployed, NASpI recipients.
7. "Mixed" is rare (e.g., employee + P.IVA) — escalate to human.
8. Once classified, transition with the employment type as trigger.

{RESPONSE_FORMAT}

Valid triggers from this state: ["dipendente", "partita_iva", "pensionato", "disoccupato", "mixed"]

Example (first message):
Per verificare a quali prodotti può accedere, ho bisogno di sapere la sua situazione lavorativa attuale:

1. Dipendente (settore pubblico o privato)
2. Lavoratore autonomo / Partita IVA
3. Pensionato/a
4. Attualmente non occupato/a

---
{{"action": "clarify", "reason": "waiting_for_employment_type"}}

Example (user said "sono un dipendente pubblico"):
Perfetto, dipendente — ottima posizione per diversi prodotti finanziari!
---
{{"action": "transition", "trigger": "dipendente", "data": {{"employment_type": "dipendente"}}}}

Example (user said "sono in pensione"):
Grazie per l'informazione. Vediamo le soluzioni disponibili per i pensionati.
---
{{"action": "transition", "trigger": "pensionato", "data": {{"employment_type": "pensionato"}}}}"""
