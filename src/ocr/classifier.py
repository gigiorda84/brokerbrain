"""Document type classification via VLM.

Single VLM call to identify the document type from an image.
Retries once on parse failure with a corrective prompt.
"""

from __future__ import annotations

import logging

from src.llm.client import llm_client
from src.models.enums import DocumentType
from src.ocr.utils import VlmParseError, parse_vlm_json
from src.schemas.ocr import ClassificationResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sei uno specialista nella classificazione di documenti finanziari italiani. "
    "Analizza l'immagine e identifica il tipo di documento."
)

CLASSIFICATION_PROMPT = (
    "Classifica questo documento italiano. Rispondi SOLO con un oggetto JSON:\n"
    '{"doc_type": "<tipo>", "confidence": <0.0-1.0>}\n\n'
    "Tipi validi:\n"
    '- "busta_paga" — cedolino stipendio / busta paga\n'
    '- "cedolino_pensione" — cedolino pensione INPS/INPDAP\n'
    '- "dichiarazione_redditi" — modello Redditi PF, 730, Unico\n'
    '- "conteggio_estintivo" — conteggio estintivo / piano ammortamento\n'
    '- "altro" — qualsiasi altro documento\n\n'
    "JSON:"
)

RETRY_PROMPT = (
    "La tua risposta precedente non era JSON valido. "
    "Rispondi SOLO con un oggetto JSON nel formato:\n"
    '{"doc_type": "<tipo>", "confidence": <0.0-1.0>}\n'
    "JSON:"
)


async def classify_document(image_base64: str) -> ClassificationResult:
    """Classify a document image into a DocumentType.

    Args:
        image_base64: Base64-encoded preprocessed image.

    Returns:
        ClassificationResult with doc_type and confidence.

    Raises:
        VlmParseError: If both attempts fail to produce valid JSON.
    """
    try:
        raw = await llm_client.chat_vision(
            system_prompt=SYSTEM_PROMPT,
            text_prompt=CLASSIFICATION_PROMPT,
            image_base64=image_base64,
        )
        return _parse_classification(raw)
    except VlmParseError:
        logger.warning("Classification parse failed, retrying with corrective prompt")

    # Retry once
    raw = await llm_client.chat_vision(
        system_prompt=SYSTEM_PROMPT,
        text_prompt=RETRY_PROMPT,
        image_base64=image_base64,
    )
    return _parse_classification(raw)


def _parse_classification(raw: str) -> ClassificationResult:
    """Parse raw VLM output into a ClassificationResult."""
    result = parse_vlm_json(raw, ClassificationResult)

    # Normalize doc_type to valid enum
    try:
        DocumentType(result.doc_type)
    except ValueError:
        result = ClassificationResult(doc_type=DocumentType.ALTRO, confidence=result.confidence * 0.5)

    return result
