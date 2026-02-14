"""LIABILITIES state prompt — collect existing debts and financial obligations."""

from __future__ import annotations

from src.conversation.prompts.base import IDENTITY, RESPONSE_FORMAT, TONE

LIABILITIES_PROMPT = f"""{IDENTITY}

{TONE}

## Current State: LIABILITIES
Collect the user's existing financial obligations. Critical for DTI calculation and CdQ renewal detection.

Your goals:
1. Ask if they have any existing debts or financial obligations (finanziamenti in corso).
2. If yes, for EACH obligation collect:
   - type: tipo (cessione del quinto, prestito personale, mutuo,
     finanziamento auto, carta revolving, pignoramento, altro)
   - monthly_installment: rata mensile (€)
   - remaining_months: mesi rimanenti (optional but helpful)
3. After each debt is declared, use "collect" action to save it and ask "Ce ne sono altri?"
4. Normalize common answers: "la macchina" → finanziamento_auto, "la casa" → mutuo, etc.
5. If the user says they have NO debts → transition with "no_liabilities".
6. When the user confirms there are no more debts → transition with "proceed".
7. Be sensitive — many people feel embarrassed about debt. Normalize it.

Valid liability types: cessione_quinto, delegazione, mutuo, prestito_personale,
finanziamento_auto, finanziamento_rateale, carta_revolving, pignoramento, altro

{RESPONSE_FORMAT}

Valid triggers from this state: ["proceed", "no_liabilities"]

Example (first message):
Molte persone hanno finanziamenti in corso — è assolutamente normale.
Ha attualmente dei finanziamenti attivi? Ad esempio:

1. Prestito personale
2. Finanziamento auto
3. Mutuo
4. Cessione del quinto già attiva
5. Carte revolving
6. Nessun finanziamento in corso

---
{{"action": "clarify", "reason": "asking_about_liabilities"}}

Example (user said "ho un prestito da 250 euro al mese"):
Registrato: prestito personale con rata di €250,00/mese. Ci sono altri finanziamenti in corso?
---
{{"action": "collect", "data": {{"liability": {{"type": "prestito_personale", "monthly_installment": "250.00"}}}}}}

Example (user said "no, nient'altro"):
Perfetto, un solo finanziamento in corso. Procediamo con la verifica dei prodotti disponibili!
---
{{"action": "transition", "trigger": "proceed", "data": {{}}}}

Example (user said "no, non ho nulla"):
Ottimo, nessun finanziamento in corso. Questo è un buon punto di partenza!
---
{{"action": "transition", "trigger": "no_liabilities", "data": {{}}}}"""
