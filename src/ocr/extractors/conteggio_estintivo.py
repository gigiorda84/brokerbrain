"""Conteggio estintivo (loan payoff statement) data extraction via VLM."""

from __future__ import annotations

import logging

from src.llm.client import llm_client
from src.ocr.utils import VlmParseError, parse_vlm_json
from src.schemas.ocr import LoanDocumentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sei uno specialista OCR per documenti finanziari italiani. "
    "Estrai con precisione i dati dal conteggio estintivo o piano di ammortamento."
)

EXTRACTION_PROMPT = (
    "Estrai i seguenti campi dal conteggio estintivo. Rispondi SOLO con un oggetto JSON.\n"
    "Se un campo non è visibile, usa null.\n\n"
    "Campi richiesti:\n"
    '- "borrower_name": nome e cognome del debitore\n'
    '- "codice_fiscale": codice fiscale (16 caratteri)\n'
    '- "lender_name": nome dell\'istituto finanziario / cessionario\n'
    '- "loan_type": tipo di finanziamento tra:\n'
    '    "cessione_quinto", "delegazione", "mutuo", "prestito_personale",\n'
    '    "finanziamento_auto", "finanziamento_rateale", "carta_revolving", "altro"\n'
    '- "original_amount": importo originale finanziato (numero)\n'
    '- "residual_debt": debito residuo / montante residuo (numero)\n'
    '- "monthly_installment": rata mensile (numero)\n'
    '- "total_installments": numero totale rate (numero intero)\n'
    '- "paid_installments": rate già pagate (numero intero)\n'
    '- "remaining_installments": rate residue (numero intero)\n'
    '- "start_date": data inizio finanziamento (DD/MM/YYYY)\n'
    '- "maturity_date": data scadenza / fine ammortamento (DD/MM/YYYY)\n'
    '- "confidence": oggetto con confidenza per campo (0.0-1.0)\n\n'
    "JSON:"
)

RETRY_PROMPT = (
    "La tua risposta precedente non era JSON valido. "
    "Rispondi SOLO con un oggetto JSON con i campi del conteggio estintivo. "
    "Usa null per i campi non visibili.\n"
    "JSON:"
)


async def extract(image_base64: str) -> LoanDocumentResult:
    """Extract loan payoff data from a preprocessed image.

    Args:
        image_base64: Base64-encoded preprocessed image.

    Returns:
        LoanDocumentResult with extracted fields and confidence scores.

    Raises:
        VlmParseError: If both attempts fail to produce valid JSON.
    """
    try:
        raw = await llm_client.chat_vision(
            system_prompt=SYSTEM_PROMPT,
            text_prompt=EXTRACTION_PROMPT,
            image_base64=image_base64,
        )
        return parse_vlm_json(raw, LoanDocumentResult)
    except VlmParseError:
        logger.warning("Conteggio estintivo extraction parse failed, retrying")

    raw = await llm_client.chat_vision(
        system_prompt=SYSTEM_PROMPT,
        text_prompt=RETRY_PROMPT,
        image_base64=image_base64,
    )
    return parse_vlm_json(raw, LoanDocumentResult)
