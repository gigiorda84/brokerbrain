"""Tests for the OCR pipeline orchestrator — mocks for LLM and events."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from src.models.enums import DocumentType
from src.ocr.pipeline import process_document
from src.ocr.utils import VlmParseError
from src.schemas.ocr import (
    BustaPagaResult,
    ClassificationResult,
    OcrResult,
)


def _make_test_image() -> bytes:
    """Create a minimal valid JPEG for testing."""
    img = Image.new("RGB", (200, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def session_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def mock_emit():
    with patch("src.ocr.pipeline.emit", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture()
def mock_ensure_model():
    with patch("src.ocr.pipeline.llm_client.ensure_model", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture()
def mock_classify():
    with patch("src.ocr.pipeline.classify_document", new_callable=AsyncMock) as m:
        yield m


def _mock_extractor(doc_type: DocumentType):
    """Patch the EXTRACTORS dict entry for a given DocumentType."""
    mock = AsyncMock()
    return patch.dict("src.ocr.pipeline.EXTRACTORS", {doc_type: mock}), mock


class TestPipelineHappyPath:
    @pytest.mark.asyncio()
    async def test_busta_paga_full_flow(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock, mock_classify: AsyncMock
    ) -> None:
        mock_classify.return_value = ClassificationResult(
            doc_type=DocumentType.BUSTA_PAGA, confidence=0.95
        )

        extraction = BustaPagaResult(
            employee_name="Mario Rossi",
            codice_fiscale="RSSMRA85H12F205Y",
            gross_salary=Decimal("2500"),
            net_salary=Decimal("1800"),
            confidence={
                "employee_name": 0.95,
                "codice_fiscale": 0.90,
                "gross_salary": 0.92,
                "net_salary": 0.88,
            },
        )

        patcher, mock_extract = _mock_extractor(DocumentType.BUSTA_PAGA)
        mock_extract.return_value = extraction
        with patcher:
            result = await process_document(_make_test_image(), session_id)

        assert isinstance(result, OcrResult)
        assert result.error is None
        assert result.doc_type == DocumentType.BUSTA_PAGA
        assert result.extraction_result is not None
        assert result.overall_confidence > 0
        assert result.processing_time_ms >= 0
        assert mock_ensure_model.call_count >= 1


class TestPipelineClassification:
    @pytest.mark.asyncio()
    async def test_low_confidence_uses_hint(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock, mock_classify: AsyncMock
    ) -> None:
        mock_classify.return_value = ClassificationResult(
            doc_type=DocumentType.ALTRO, confidence=0.40
        )

        extraction = BustaPagaResult(
            gross_salary=Decimal("2000"),
            net_salary=Decimal("1500"),
            confidence={"gross_salary": 0.90, "net_salary": 0.85},
        )

        patcher, mock_extract = _mock_extractor(DocumentType.BUSTA_PAGA)
        mock_extract.return_value = extraction
        with patcher:
            result = await process_document(
                _make_test_image(), session_id,
                expected_doc_type=DocumentType.BUSTA_PAGA,
            )

        assert result.doc_type == DocumentType.BUSTA_PAGA
        assert result.error is None


class TestPipelineUnsupportedType:
    @pytest.mark.asyncio()
    async def test_unsupported_doc_type_returns_error(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock, mock_classify: AsyncMock
    ) -> None:
        mock_classify.return_value = ClassificationResult(
            doc_type=DocumentType.DOCUMENTO_IDENTITA, confidence=0.95
        )

        result = await process_document(_make_test_image(), session_id)
        assert result.error is not None
        assert "non supportato" in result.error


class TestPipelineRetryAndEscalation:
    @pytest.mark.asyncio()
    async def test_non_json_retry_succeeds(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock, mock_classify: AsyncMock
    ) -> None:
        mock_classify.return_value = ClassificationResult(
            doc_type=DocumentType.BUSTA_PAGA, confidence=0.95
        )

        extraction = BustaPagaResult(
            gross_salary=Decimal("2000"),
            confidence={"gross_salary": 0.90},
        )

        patcher, mock_extract = _mock_extractor(DocumentType.BUSTA_PAGA)
        # First call fails, second succeeds
        mock_extract.side_effect = [
            VlmParseError("bad json", raw_output="not json"),
            extraction,
        ]
        with patcher:
            result = await process_document(_make_test_image(), session_id)

        assert result.error is None
        assert result.extraction_result is not None

    @pytest.mark.asyncio()
    async def test_two_failures_escalates(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock, mock_classify: AsyncMock
    ) -> None:
        mock_classify.return_value = ClassificationResult(
            doc_type=DocumentType.BUSTA_PAGA, confidence=0.95
        )

        patcher, mock_extract = _mock_extractor(DocumentType.BUSTA_PAGA)
        mock_extract.side_effect = VlmParseError("bad json", raw_output="not json")
        with patcher:
            result = await process_document(_make_test_image(), session_id)

        assert result.error is not None
        assert "operatore" in result.error
        # Should have emitted SESSION_ESCALATED
        escalated_events = [
            call for call in mock_emit.call_args_list
            if hasattr(call.args[0], "event_type") and "escalated" in call.args[0].event_type.value
        ]
        assert len(escalated_events) > 0


class TestPipelineModelSwap:
    @pytest.mark.asyncio()
    async def test_model_swapped_back_on_error(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock, mock_classify: AsyncMock
    ) -> None:
        mock_classify.side_effect = Exception("VLM crashed")

        result = await process_document(
            _make_test_image(), session_id,
            expected_doc_type=DocumentType.BUSTA_PAGA,
        )

        # Model swap-back should have been called in finally block
        assert len(mock_ensure_model.call_args_list) >= 2  # vision + conversation swap-back


class TestPipelineCorruptImage:
    @pytest.mark.asyncio()
    async def test_corrupt_image_returns_error(
        self, session_id: uuid.UUID, mock_emit: AsyncMock, mock_ensure_model: AsyncMock
    ) -> None:
        result = await process_document(b"corrupt data", session_id)
        assert result.error is not None
        assert "Non riesco a leggere" in result.error
