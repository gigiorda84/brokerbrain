"""OCR pipeline orchestrator.

Main entry point for document processing. Coordinates preprocessing,
classification, extraction, and validation. Handles model swapping
and error recovery. No DB access — caller persists results.
"""

from __future__ import annotations

import logging
import time
import uuid

from src.admin.events import emit
from src.config import settings
from src.llm.client import llm_client
from src.models.enums import DocumentType
from src.ocr.classifier import classify_document
from src.ocr.extractors import EXTRACTORS, SUPPORTED_TYPES
from src.ocr.preprocessor import ImagePreprocessingError, preprocess_image
from src.ocr.utils import VlmParseError
from src.ocr.validator import validate_extraction
from src.schemas.events import EventType, SystemEvent
from src.schemas.ocr import OcrResult

logger = logging.getLogger(__name__)

# Classification confidence threshold for trusting the VLM classification
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.80


async def process_document(
    raw_image_bytes: bytes,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    expected_doc_type: DocumentType | None = None,
) -> OcrResult:
    """Process a document image through the full OCR pipeline.

    Flow:
        1. Preprocess image
        2. Ensure vision model loaded
        3. Classify document type
        4. Extract data via type-specific extractor
        5. Validate extraction
        6. Build OcrResult
        7. Swap back to conversation model

    Args:
        raw_image_bytes: Raw image bytes from the user.
        session_id: Current conversation session ID.
        user_id: Optional user ID for event context.
        expected_doc_type: Optional hint from conversation FSM.

    Returns:
        OcrResult with extraction data or error information.
        Never raises — all errors are captured in the result.
    """
    start = time.monotonic()
    vlm_failures = 0

    await emit(SystemEvent(
        event_type=EventType.DOCUMENT_RECEIVED,
        session_id=session_id,
        user_id=user_id,
        data={"image_size_bytes": len(raw_image_bytes)},
        source_module="ocr.pipeline",
    ))

    try:
        # 1. Preprocess
        try:
            preprocessed = preprocess_image(raw_image_bytes)
        except ImagePreprocessingError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return OcrResult(error=exc.user_message, processing_time_ms=elapsed_ms)

        # 2. Ensure vision model
        await emit(SystemEvent(
            event_type=EventType.OCR_STARTED,
            session_id=session_id,
            user_id=user_id,
            data={
                "original_size": f"{preprocessed.original_width}x{preprocessed.original_height}",
                "final_size": f"{preprocessed.final_width}x{preprocessed.final_height}",
            },
            source_module="ocr.pipeline",
        ))
        await llm_client.ensure_model(settings.llm.vision_model)

        # 3. Classify document
        try:
            classification = await classify_document(preprocessed.base64_str)
            vlm_failures = 0
        except (VlmParseError, Exception) as exc:
            vlm_failures += 1
            logger.warning("Classification failed: %s", exc)
            if expected_doc_type is not None:
                classification = None
            else:
                # Try once more
                try:
                    classification = await classify_document(preprocessed.base64_str)
                    vlm_failures = 0
                except Exception:
                    vlm_failures += 1
                    return await _handle_escalation(vlm_failures, session_id, user_id, start)

        # Determine final doc_type
        if classification is not None:
            doc_type = DocumentType(classification.doc_type)
            cls_confidence = classification.confidence
        else:
            doc_type = DocumentType.ALTRO
            cls_confidence = 0.0

        # If low confidence and hint provided, use hint
        if cls_confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD and expected_doc_type is not None:
            doc_type = expected_doc_type
            logger.info("Using expected doc_type hint: %s (classification confidence: %.2f)", doc_type, cls_confidence)

        await emit(SystemEvent(
            event_type=EventType.DOCUMENT_CLASSIFIED,
            session_id=session_id,
            user_id=user_id,
            data={"doc_type": doc_type.value, "confidence": cls_confidence},
            source_module="ocr.pipeline",
        ))

        # 4. Extract data
        if doc_type not in SUPPORTED_TYPES:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return OcrResult(
                doc_type=doc_type,
                processing_time_ms=elapsed_ms,
                error=f"Tipo di documento non supportato: {doc_type.value}",
            )

        extractor = EXTRACTORS[doc_type]
        try:
            extraction_result = await extractor(preprocessed.base64_str)
            vlm_failures = 0
        except (VlmParseError, Exception) as exc:
            vlm_failures += 1
            logger.warning("Extraction failed (attempt 1): %s", exc)
            try:
                extraction_result = await extractor(preprocessed.base64_str)
                vlm_failures = 0
            except Exception:
                vlm_failures += 1
                return await _handle_escalation(vlm_failures, session_id, user_id, start, doc_type=doc_type)

        # 5. Validate
        validation = validate_extraction(extraction_result, doc_type)

        # Merge confidence overrides into extraction result
        merged_confidence = dict(extraction_result.confidence)
        merged_confidence.update(validation.confidence_overrides)

        # Compute overall confidence
        overall = sum(merged_confidence.values()) / len(merged_confidence) if merged_confidence else 0.0

        elapsed_ms = int((time.monotonic() - start) * 1000)

        ocr_result = OcrResult(
            doc_type=doc_type,
            extraction_result=extraction_result,
            overall_confidence=round(overall, 3),
            fields_needing_confirmation=validation.fields_needing_confirmation,
            fields_needing_admin_review=validation.fields_needing_admin_review,
            processing_time_ms=elapsed_ms,
        )

        await emit(SystemEvent(
            event_type=EventType.OCR_COMPLETED,
            session_id=session_id,
            user_id=user_id,
            data={
                "doc_type": doc_type.value,
                "overall_confidence": ocr_result.overall_confidence,
                "fields_extracted": len(merged_confidence),
                "processing_time_ms": elapsed_ms,
            },
            source_module="ocr.pipeline",
        ))

        await emit(SystemEvent(
            event_type=EventType.DATA_EXTRACTED,
            session_id=session_id,
            user_id=user_id,
            data={
                "doc_type": doc_type.value,
                "fields_needing_confirmation": validation.fields_needing_confirmation,
                "fields_needing_admin_review": validation.fields_needing_admin_review,
                "warnings": validation.warnings,
            },
            source_module="ocr.pipeline",
        ))

        return ocr_result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.exception("Unexpected error in OCR pipeline")
        await emit(SystemEvent(
            event_type=EventType.OCR_FAILED,
            session_id=session_id,
            user_id=user_id,
            data={"error": str(exc), "processing_time_ms": elapsed_ms},
            source_module="ocr.pipeline",
        ))
        return OcrResult(
            error="Errore durante l'elaborazione del documento. Riprovi più tardi.",
            processing_time_ms=elapsed_ms,
        )

    finally:
        # Always swap back to conversation model
        try:
            await llm_client.ensure_model(settings.llm.conversation_model)
        except Exception:
            logger.exception("Failed to swap back to conversation model")


async def _handle_escalation(
    vlm_failures: int,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None,
    start: float,
    doc_type: DocumentType | None = None,
) -> OcrResult:
    """Build an error OcrResult and emit escalation if 2+ VLM failures."""
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if vlm_failures >= 2:
        logger.error("2 consecutive VLM failures — escalating session %s", session_id)
        await emit(SystemEvent(
            event_type=EventType.SESSION_ESCALATED,
            session_id=session_id,
            user_id=user_id,
            data={"reason": "consecutive_vlm_failures", "failure_count": vlm_failures},
            source_module="ocr.pipeline",
        ))
    return OcrResult(
        doc_type=doc_type,
        processing_time_ms=elapsed_ms,
        error="Non riesco a elaborare il documento. Un operatore verificherà la sua richiesta.",
    )
