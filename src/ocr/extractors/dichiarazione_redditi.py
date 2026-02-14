"""Dichiarazione redditi (tax return) data extraction via VLM."""

from __future__ import annotations

import logging

from src.llm.client import llm_client
from src.ocr.utils import VlmParseError, parse_vlm_json
from src.schemas.ocr import DichiarazioneRedditiResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sei uno specialista OCR per documenti finanziari italiani. "
    "Estrai con precisione i dati dalla dichiarazione dei redditi."
)

EXTRACTION_PROMPT = (
    "Estrai i seguenti campi dalla dichiarazione dei redditi. Rispondi SOLO con un oggetto JSON.\n"
    "Se un campo non è visibile, usa null.\n\n"
    "Campi richiesti:\n"
    '- "taxpayer_name": nome e cognome del contribuente\n'
    '- "codice_fiscale": codice fiscale (16 caratteri)\n'
    '- "partita_iva": partita IVA (11 cifre)\n'
    '- "ateco_code": codice ATECO (formato XX.XX.XX)\n'
    '- "tax_regime": "forfettario", "ordinario" o "semplificato"\n'
    '- "tax_year": anno d\'imposta (numero intero, es. 2024)\n'
    '- "reddito_imponibile": reddito imponibile (numero)\n'
    '- "reddito_lordo": reddito lordo complessivo (numero)\n'
    '- "imposta_netta": imposta netta dovuta (numero)\n'
    '- "volume_affari": volume d\'affari IVA (numero)\n'
    '- "confidence": oggetto con confidenza per campo (0.0-1.0)\n\n'
    "JSON:"
)

RETRY_PROMPT = (
    "La tua risposta precedente non era JSON valido. "
    "Rispondi SOLO con un oggetto JSON con i campi della dichiarazione redditi. "
    "Usa null per i campi non visibili.\n"
    "JSON:"
)


async def extract(image_base64: str) -> DichiarazioneRedditiResult:
    """Extract tax return data from a preprocessed image.

    Args:
        image_base64: Base64-encoded preprocessed image.

    Returns:
        DichiarazioneRedditiResult with extracted fields and confidence scores.

    Raises:
        VlmParseError: If both attempts fail to produce valid JSON.
    """
    try:
        raw = await llm_client.chat_vision(
            system_prompt=SYSTEM_PROMPT,
            text_prompt=EXTRACTION_PROMPT,
            image_base64=image_base64,
        )
        return parse_vlm_json(raw, DichiarazioneRedditiResult)
    except VlmParseError:
        logger.warning("Dichiarazione redditi extraction parse failed, retrying")

    raw = await llm_client.chat_vision(
        system_prompt=SYSTEM_PROMPT,
        text_prompt=RETRY_PROMPT,
        image_base64=image_base64,
    )
    return parse_vlm_json(raw, DichiarazioneRedditiResult)
