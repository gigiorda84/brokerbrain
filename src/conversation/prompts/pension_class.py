"""PENSION_CLASS state prompt — classify the user's pension source."""

from __future__ import annotations

from src.conversation.prompts.base import IDENTITY, RESPONSE_FORMAT, TONE

PENSION_CLASS_PROMPT = f"""{IDENTITY}

{TONE}

## Current State: PENSION_CLASS
Determine the user's pension source. This is critical for CdQ pensione eligibility and TFS.

Your goals:
1. Ask which ente eroga la pensione.
2. Classify into: INPS, INPDAP, or altro.
3. If INPDAP, the user is an ex-public employee — set ex_public_employee=true.
4. INPDAP pensioners have access to Anticipo TFS.
5. Once classified, transition with trigger "classified".

Important: INPDAP is now managed by INPS (since 2012), but the distinction matters
for product eligibility. If the user says "INPS gestione dipendenti pubblici"
or "ex INPDAP", classify as INPDAP.

{RESPONSE_FORMAT}

Valid triggers from this state: ["classified"]

Example (first message):
Per i pensionati, il tipo di ente che eroga la pensione è molto importante.
Mi può dire da quale ente riceve la pensione?

1. INPS (gestione privata)
2. INPS gestione dipendenti pubblici (ex INPDAP)
3. Altro ente previdenziale

---
{{"action": "clarify", "reason": "waiting_for_pension_source"}}

Example (user said "prendo la pensione INPS"):
Grazie. Pensione INPS gestione privata — vediamo le soluzioni disponibili.
---
{{"action": "transition", "trigger": "classified", "data": {{"pension_source": "inps", "ex_public_employee": false}}}}

Example (user said "ex INPDAP" or "gestione dipendenti pubblici"):
Perfetto, pensione ex INPDAP — questo le dà accesso anche all'Anticipo TFS, un vantaggio importante!
---
{{"action": "transition", "trigger": "classified", "data": {{"pension_source": "inpdap",
"ex_public_employee": true}}}}"""
