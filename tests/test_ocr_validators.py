"""Tests for OCR post-extraction validators — no mocks, construct results directly."""

from __future__ import annotations

from decimal import Decimal

from src.models.enums import DocumentType
from src.ocr.validator import (
    ADMIN_REVIEW_THRESHOLD,
    CONFIRMATION_THRESHOLD,
    ValidationResult,
    validate_extraction,
)
from src.schemas.ocr import (
    BustaPagaResult,
    CedolinoPensioneResult,
    DeductionSet,
    DichiarazioneRedditiResult,
    LoanDocumentResult,
)


class TestCfValidation:
    def test_valid_cf_gets_confidence_1(self) -> None:
        # RSSMRA85H12F205Y is valid
        result = BustaPagaResult(
            codice_fiscale="RSSMRA85H12F205Y",
            confidence={"codice_fiscale": 0.80},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert vr.confidence_overrides["codice_fiscale"] == 1.0

    def test_invalid_cf_gets_low_confidence(self) -> None:
        result = BustaPagaResult(
            codice_fiscale="RSSMRA85H12F205X",  # wrong checksum
            confidence={"codice_fiscale": 0.80},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert vr.confidence_overrides["codice_fiscale"] == 0.30
        assert any("checksum" in w for w in vr.warnings)


class TestSalaryValidation:
    def test_salary_in_range(self) -> None:
        result = BustaPagaResult(
            gross_salary=Decimal("2500"),
            net_salary=Decimal("1800"),
            confidence={"gross_salary": 0.90, "net_salary": 0.90},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert "gross_salary" not in vr.confidence_overrides
        assert "net_salary" not in vr.confidence_overrides

    def test_salary_out_of_range(self) -> None:
        result = BustaPagaResult(
            gross_salary=Decimal("100000"),
            confidence={"gross_salary": 0.90},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert vr.confidence_overrides["gross_salary"] == 0.30

    def test_net_exceeds_gross(self) -> None:
        result = BustaPagaResult(
            gross_salary=Decimal("1800"),
            net_salary=Decimal("2500"),
            confidence={"gross_salary": 0.90, "net_salary": 0.90},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert vr.confidence_overrides["net_salary"] == 0.30
        assert vr.confidence_overrides["gross_salary"] == 0.30
        assert any("exceeds gross" in w for w in vr.warnings)


class TestDateValidation:
    def test_future_hiring_date_flagged(self) -> None:
        result = BustaPagaResult(
            hiring_date="01/01/2099",
            confidence={"hiring_date": 0.90},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert vr.confidence_overrides["hiring_date"] == 0.30
        assert any("future" in w for w in vr.warnings)

    def test_valid_hiring_date_passes(self) -> None:
        result = BustaPagaResult(
            hiring_date="15/03/2020",
            confidence={"hiring_date": 0.90},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert "hiring_date" not in vr.confidence_overrides


class TestInstallmentConsistency:
    def test_consistent_installments(self) -> None:
        result = LoanDocumentResult(
            total_installments=120,
            paid_installments=48,
            remaining_installments=72,
            confidence={
                "total_installments": 0.90,
                "paid_installments": 0.90,
                "remaining_installments": 0.90,
            },
        )
        vr = validate_extraction(result, DocumentType.CONTEGGIO_ESTINTIVO)
        assert "total_installments" not in vr.confidence_overrides

    def test_inconsistent_installments(self) -> None:
        result = LoanDocumentResult(
            total_installments=120,
            paid_installments=48,
            remaining_installments=80,  # 48+80=128 != 120
            confidence={
                "total_installments": 0.90,
                "paid_installments": 0.90,
                "remaining_installments": 0.90,
            },
        )
        vr = validate_extraction(result, DocumentType.CONTEGGIO_ESTINTIVO)
        assert vr.confidence_overrides["total_installments"] == 0.40
        assert any("mismatch" in w for w in vr.warnings)


class TestThresholdClassification:
    def test_below_admin_threshold_flagged(self) -> None:
        result = BustaPagaResult(
            confidence={"net_salary": 0.40},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert "net_salary" in vr.fields_needing_admin_review

    def test_below_confirmation_threshold_flagged(self) -> None:
        result = BustaPagaResult(
            confidence={"net_salary": 0.60},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert "net_salary" in vr.fields_needing_confirmation
        assert "net_salary" not in vr.fields_needing_admin_review

    def test_above_confirmation_threshold_ok(self) -> None:
        result = BustaPagaResult(
            confidence={"net_salary": 0.85},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert "net_salary" not in vr.fields_needing_confirmation
        assert "net_salary" not in vr.fields_needing_admin_review


class TestPartitaIvaValidation:
    def test_valid_piva_format(self) -> None:
        result = DichiarazioneRedditiResult(
            partita_iva="08154920014",
            confidence={"partita_iva": 0.90},
        )
        vr = validate_extraction(result, DocumentType.DICHIARAZIONE_REDDITI)
        assert "partita_iva" not in vr.confidence_overrides

    def test_invalid_piva_format(self) -> None:
        result = DichiarazioneRedditiResult(
            partita_iva="123ABC",
            confidence={"partita_iva": 0.90},
        )
        vr = validate_extraction(result, DocumentType.DICHIARAZIONE_REDDITI)
        assert vr.confidence_overrides["partita_iva"] == 0.30


class TestDeductionValidation:
    def test_deduction_exceeds_net(self) -> None:
        result = BustaPagaResult(
            net_salary=Decimal("1500"),
            deductions=DeductionSet(cessione_del_quinto=Decimal("2000")),
            confidence={"net_salary": 0.90},
        )
        vr = validate_extraction(result, DocumentType.BUSTA_PAGA)
        assert vr.confidence_overrides["deductions.cessione_del_quinto"] == 0.40
        assert any("exceeds net salary" in w for w in vr.warnings)
