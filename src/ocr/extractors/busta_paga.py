"""Busta paga (payslip) data extraction via VLM."""

from __future__ import annotations

import logging

from src.llm.client import llm_client
from src.ocr.utils import VlmParseError, parse_vlm_json
from src.schemas.ocr import BustaPagaResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sei uno specialista OCR per documenti finanziari italiani. "
    "Estrai con precisione i dati dalla busta paga."
)

EXTRACTION_PROMPT = (
    "Estrai i seguenti campi dalla busta paga. Rispondi SOLO con un oggetto JSON.\n"
    "Se un campo non è visibile, usa null.\n\n"
    "Campi richiesti:\n"
    '- "employee_name": nome e cognome del dipendente\n'
    '- "codice_fiscale": codice fiscale (16 caratteri)\n'
    '- "employer_name": nome del datore di lavoro\n'
    '- "employer_category": "statale", "pubblico", "privato" o "parapubblico"\n'
    '- "contract_type": "indeterminato", "determinato" o "apprendistato"\n'
    '- "ccnl": contratto collettivo applicato\n'
    '- "hiring_date": data di assunzione (DD/MM/YYYY con anno a 4 cifre, es. 01/03/2015). NON confondere con la data di nascita.\n'
    '- "pay_period": periodo retributivo (MM/YYYY)\n'
    '- "ral": retribuzione annua lorda (numero)\n'
    '- "gross_salary": retribuzione lorda mensile (numero)\n'
    '- "net_salary": retribuzione netta mensile (numero)\n'
    '- "tfr_accrued": TFR maturato (numero)\n'
    '- "seniority_months": anzianità in mesi (numero intero)\n'
    '- "deductions": oggetto con le trattenute:\n'
    '    - "cessione_del_quinto": importo cessione del quinto (numero o null)\n'
    '    - "delegazione": importo delegazione di pagamento (numero o null)\n'
    '    - "pignoramento": importo pignoramento (numero o null)\n'
    '    - "other": lista di {"description": "...", "amount": numero}\n'
    '- "confidence": oggetto con confidenza per campo (0.0-1.0)\n\n'
    "JSON:"
)

RETRY_PROMPT = (
    "La tua risposta precedente non era JSON valido. "
    "Rispondi SOLO con un oggetto JSON con i campi della busta paga. "
    "Usa null per i campi non visibili.\n"
    "JSON:"
)


async def extract(image_base64: str) -> BustaPagaResult:
    """Extract payslip data from a preprocessed image.

    Args:
        image_base64: Base64-encoded preprocessed image.

    Returns:
        BustaPagaResult with extracted fields and confidence scores.

    Raises:
        VlmParseError: If both attempts fail to produce valid JSON.
    """
    try:
        raw = await llm_client.chat_vision(
            system_prompt=SYSTEM_PROMPT,
            text_prompt=EXTRACTION_PROMPT,
            image_base64=image_base64,
        )
        return parse_vlm_json(raw, BustaPagaResult)
    except VlmParseError:
        logger.warning("Busta paga extraction parse failed, retrying")

    raw = await llm_client.chat_vision(
        system_prompt=SYSTEM_PROMPT,
        text_prompt=RETRY_PROMPT,
        image_base64=image_base64,
    )
    return parse_vlm_json(raw, BustaPagaResult)
