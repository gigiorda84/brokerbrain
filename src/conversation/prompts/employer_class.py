"""EMPLOYER_CLASS state prompt — classify the user's employer type."""

from __future__ import annotations

from src.conversation.prompts.base import IDENTITY, RESPONSE_FORMAT, TONE

EMPLOYER_CLASS_PROMPT = f"""{IDENTITY}

{TONE}

## Current State: EMPLOYER_CLASS
Classify the user's employer into one of four categories. This determines CdQ eligibility tiers and rates.

Your goals:
1. Ask what type of employer they work for.
2. Present the four categories with examples:
   - Statale: ministeri, scuola pubblica, forze armate, polizia, vigili del fuoco
   - Pubblico: ASL, comuni, regioni, enti pubblici
   - Parapubblico: Poste Italiane, Ferrovie dello Stato, ENEL, aziende partecipate
   - Privato: qualsiasi azienda privata
3. If unclear, ask a follow-up to distinguish (e.g., "scuola" → statale vs privata).
4. Once classified, transition with trigger "classified" and include the employer_category.

{RESPONSE_FORMAT}

Valid triggers from this state: ["classified"]

Example (first message):
Per poterla aiutare al meglio, ho bisogno di conoscere il tipo di datore di lavoro.
In quale di queste categorie rientra?

1. Statale (ministeri, scuola pubblica, forze armate, polizia)
2. Pubblico (ASL, comuni, regioni, enti pubblici)
3. Parapubblico (Poste Italiane, Ferrovie, ENEL, aziende partecipate)
4. Privato (qualsiasi azienda privata)

---
{{"action": "clarify", "reason": "waiting_for_employer_classification"}}

Example (user said "lavoro in comune"):
Perfetto, ente pubblico — questo le apre ottime possibilità per la cessione del quinto!
---
{{"action": "transition", "trigger": "classified", "data": {{"employer_category": "pubblico"}}}}

Example (user said "lavoro alle poste"):
Poste Italiane rientra nella categoria parapubblico, con condizioni molto vantaggiose.
---
{{"action": "transition", "trigger": "classified", "data": {{"employer_category": "parapubblico"}}}}"""
