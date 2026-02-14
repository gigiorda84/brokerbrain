"""Cedolino pensione (pension slip) data extraction via VLM."""

from __future__ import annotations

import logging

from src.llm.client import llm_client
from src.ocr.utils import VlmParseError, parse_vlm_json
from src.schemas.ocr import CedolinoPensioneResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sei uno specialista OCR per documenti finanziari italiani. "
    "Estrai con precisione i dati dal cedolino pensione."
)

EXTRACTION_PROMPT = (
    "Estrai i seguenti campi dal cedolino pensione. Rispondi SOLO con un oggetto JSON.\n"
    "Se un campo non è visibile, usa null.\n\n"
    "IMPORTANTE: il campo 'net_pension_before_cdq' è il netto pensione PRIMA di eventuali "
    "trattenute per cessione del quinto. Se non c'è cessione del quinto, coincide con 'net_pension'.\n\n"
    "Campi richiesti:\n"
    '- "pensioner_name": nome e cognome del pensionato\n'
    '- "codice_fiscale": codice fiscale (16 caratteri)\n'
    '- "pension_source": "inps", "inpdap" o "altro"\n'
    '- "pension_type": "vecchiaia", "anticipata", "invalidita", "superstiti" o "sociale"\n'
    '- "pay_period": periodo (MM/YYYY)\n'
    '- "gross_pension": pensione lorda mensile (numero)\n'
    '- "net_pension": pensione netta mensile (numero, dopo tutte le trattenute)\n'
    '- "net_pension_before_cdq": netto prima della cessione del quinto (numero)\n'
    '- "irpef_withheld": IRPEF trattenuta (numero)\n'
    '- "addizionale_regionale": addizionale regionale (numero)\n'
    '- "deductions": oggetto con le trattenute:\n'
    '    - "cessione_del_quinto": importo cessione del quinto (numero o null)\n'
    '    - "delegazione": importo delegazione (numero o null)\n'
    '    - "pignoramento": importo pignoramento (numero o null)\n'
    '    - "other": lista di {"description": "...", "amount": numero}\n'
    '- "confidence": oggetto con confidenza per campo (0.0-1.0)\n\n'
    "JSON:"
)

RETRY_PROMPT = (
    "La tua risposta precedente non era JSON valido. "
    "Rispondi SOLO con un oggetto JSON con i campi del cedolino pensione. "
    "Usa null per i campi non visibili.\n"
    "JSON:"
)


async def extract(image_base64: str) -> CedolinoPensioneResult:
    """Extract pension slip data from a preprocessed image.

    Args:
        image_base64: Base64-encoded preprocessed image.

    Returns:
        CedolinoPensioneResult with extracted fields and confidence scores.

    Raises:
        VlmParseError: If both attempts fail to produce valid JSON.
    """
    try:
        raw = await llm_client.chat_vision(
            system_prompt=SYSTEM_PROMPT,
            text_prompt=EXTRACTION_PROMPT,
            image_base64=image_base64,
        )
        return parse_vlm_json(raw, CedolinoPensioneResult)
    except VlmParseError:
        logger.warning("Cedolino pensione extraction parse failed, retrying")

    raw = await llm_client.chat_vision(
        system_prompt=SYSTEM_PROMPT,
        text_prompt=RETRY_PROMPT,
        image_base64=image_base64,
    )
    return parse_vlm_json(raw, CedolinoPensioneResult)
