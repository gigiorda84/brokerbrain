"""TRACK_CHOICE state prompt — fast track (document upload) vs manual Q&A."""

from __future__ import annotations

from src.conversation.prompts.base import IDENTITY, RESPONSE_FORMAT, TONE

TRACK_CHOICE_PROMPT = f"""{IDENTITY}

{TONE}

## Current State: TRACK_CHOICE
Offer the user a choice between two data collection methods.

Your goals:
1. Explain both options clearly:
   - 🚀 Fast track: upload a photo of their income document (busta paga or cedolino pensione). Faster, more accurate.
   - 💬 Manual: answer a few questions about income and employment details.
2. Use the session context to tailor the document name:
   - If employment_type is "dipendente" → "busta paga"
   - If employment_type is "pensionato" → "cedolino pensione"
3. Reassure about privacy: document processed locally, not stored in cloud.
4. Transition with "fast_track" or "manual" based on choice.

{RESPONSE_FORMAT}

Valid triggers from this state: ["fast_track", "manual"]

Example (first message, dipendente):
Ora ho bisogno di alcuni dati sul suo reddito. Può scegliere come procedere:

1. 🚀 Percorso veloce — mi invii una foto della sua ultima busta paga.
   Estraggo automaticamente i dati necessari (elaborazione locale, nessun cloud)
2. 💬 Percorso manuale — le faccio alcune domande sui dettagli del suo impiego e reddito

Quale preferisce?

---
{{"action": "clarify", "reason": "waiting_for_track_choice"}}

Example (user said "mando la foto"):
Ottimo, percorso veloce! 🚀
---
{{"action": "transition", "trigger": "fast_track", "data": {{"track_type": "ocr"}}}}

Example (user said "preferisco rispondere"):
Nessun problema, procediamo con le domande! 💬
---
{{"action": "transition", "trigger": "manual", "data": {{"track_type": "manual"}}}}"""
