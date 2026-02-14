"""Extractor registry — maps DocumentType to extraction functions."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from src.models.enums import DocumentType
from src.ocr.extractors import (
    busta_paga,
    cedolino_pensione,
    conteggio_estintivo,
    dichiarazione_redditi,
)
from src.schemas.ocr import ExtractionResult

# Type alias for extractor functions
ExtractorFn = Callable[[str], Coroutine[Any, Any, ExtractionResult]]

EXTRACTORS: dict[DocumentType, ExtractorFn] = {
    DocumentType.BUSTA_PAGA: busta_paga.extract,
    DocumentType.CEDOLINO_PENSIONE: cedolino_pensione.extract,
    DocumentType.DICHIARAZIONE_REDDITI: dichiarazione_redditi.extract,
    DocumentType.CONTEGGIO_ESTINTIVO: conteggio_estintivo.extract,
}

SUPPORTED_TYPES: set[DocumentType] = set(EXTRACTORS.keys())
