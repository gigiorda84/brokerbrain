"""Tests for the dossier builder."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.dossier.builder import (
    _calculate_completeness,
    _calculate_confidence,
    build_dossier,
    format_dossier_telegram,
)
from src.schemas.dossier import DossierAnagrafica, DossierLavoro


# ── Helpers ───────────────────────────────────────────────────────────


def _make_ed(field_name: str, value: str, source: str = "manual", confidence: float = 0.9) -> MagicMock:
    """Create a mock ExtractedData row."""
    ed = MagicMock()
    ed.field_name = field_name
    ed.value = value
    ed.value_encrypted = False
    ed.source = source
    ed.confidence = confidence
    return ed


def _make_session(**kwargs) -> MagicMock:
    """Create a mock session with sensible defaults."""
    session = MagicMock()
    session.id = kwargs.get("id", uuid.uuid4())
    session.employment_type = kwargs.get("employment_type", "dipendente")
    session.employer_category = kwargs.get("employer_category", "pubblico")
    session.pension_source = kwargs.get("pension_source")
    session.started_at = kwargs.get("started_at", datetime.now(UTC))
    session.extracted_data = kwargs.get("extracted_data", [])
    session.liabilities = kwargs.get("liabilities", [])
    session.dti_calculations = kwargs.get("dti_calculations", [])
    session.cdq_calculations = kwargs.get("cdq_calculations", [])
    session.product_matches = kwargs.get("product_matches", [])
    session.documents = kwargs.get("documents", [])
    session.messages = kwargs.get("messages", [])

    user = MagicMock()
    user.first_name = kwargs.get("first_name", "Mario")
    user.last_name = kwargs.get("last_name", "Rossi")
    user.phone = kwargs.get("phone", "+393331234567")
    user.email = kwargs.get("email")
    user.channel = kwargs.get("channel", "telegram")
    session.user = user

    return session


# ── Tests ─────────────────────────────────────────────────────────────


class TestBuildDossier:
    """Test full dossier assembly."""

    def test_minimal_session(self):
        session = _make_session()
        dossier = build_dossier(session)
        assert dossier.session_id == str(session.id)
        assert dossier.user_channel == "telegram"
        assert dossier.anagrafica.nome == "Mario"
        assert dossier.anagrafica.cognome == "Rossi"

    def test_with_extracted_data(self):
        session = _make_session(extracted_data=[
            _make_ed("codice_fiscale", "RSSMRA85M01H501Z"),
            _make_ed("age", "40", source="cf_decode", confidence=1.0),
            _make_ed("net_salary", "2000.00", source="ocr"),
            _make_ed("birthdate", "1985-08-01", source="cf_decode"),
            _make_ed("gender", "M", source="cf_decode"),
        ])
        dossier = build_dossier(session)
        assert dossier.anagrafica.codice_fiscale == "RSSMRA85M01H501Z"
        assert dossier.anagrafica.eta == 40
        assert dossier.lavoro.reddito_netto_mensile == Decimal("2000.00")

    def test_with_liabilities(self):
        lib = MagicMock()
        lib.type = "mutuo"
        lib.monthly_installment = Decimal("500")
        lib.remaining_months = 120
        lib.residual_amount = Decimal("50000")
        lib.lender = "Banca XYZ"
        lib.renewable = None

        session = _make_session(liabilities=[lib])
        dossier = build_dossier(session)
        assert len(dossier.impegni) == 1
        assert dossier.impegni[0].rata_mensile == Decimal("500")
        assert dossier.impegni[0].finanziatore == "Banca XYZ"

    def test_with_dti_calculation(self):
        dti = MagicMock()
        dti.current_dti = Decimal("0.3500")
        dti.projected_dti = Decimal("0.4200")

        session = _make_session(dti_calculations=[dti])
        dossier = build_dossier(session)
        assert dossier.calcoli.dti_corrente == Decimal("0.3500")
        assert dossier.calcoli.dti_proiettato == Decimal("0.4200")

    def test_with_cdq_calculation(self):
        cdq = MagicMock()
        cdq.available_cdq = Decimal("400.00")
        cdq.available_delega = Decimal("400.00")

        session = _make_session(cdq_calculations=[cdq])
        dossier = build_dossier(session)
        assert dossier.calcoli.cdq_rata_disponibile == Decimal("400.00")

    def test_with_product_matches(self):
        pm1 = MagicMock()
        pm1.product_name = "CdQ Statale"
        pm1.sub_type = None
        pm1.eligible = True
        pm1.rank = 1

        pm2 = MagicMock()
        pm2.product_name = "Mutuo Prima Casa"
        pm2.sub_type = None
        pm2.eligible = False
        pm2.rank = 2

        session = _make_session(product_matches=[pm2, pm1])
        dossier = build_dossier(session)
        # Eligible should come first
        assert dossier.prodotti[0].prodotto == "CdQ Statale"
        assert dossier.prodotti[0].idoneo is True
        assert dossier.prodotti[1].idoneo is False

    def test_with_documents(self):
        doc = MagicMock()
        doc.doc_type = "busta_paga"
        doc.original_filename = "busta_gen2026.jpg"
        doc.overall_confidence = 0.87
        doc.processing_model = "qwen2.5-vl:7b-q4_K_M"

        session = _make_session(documents=[doc])
        dossier = build_dossier(session)
        assert len(dossier.documenti) == 1
        assert dossier.documenti[0].tipo == "busta_paga"

    def test_cqs_form_prefill(self):
        session = _make_session(extracted_data=[
            _make_ed("net_salary", "2000.00"),
            _make_ed("birthdate", "01/08/1985"),
        ])
        cdq = MagicMock()
        cdq.available_cdq = Decimal("400.00")
        cdq.available_delega = Decimal("400.00")
        session.cdq_calculations = [cdq]

        dossier = build_dossier(session)
        assert dossier.form_cqs is not None
        assert dossier.form_cqs.nome == "Mario"
        assert dossier.form_cqs.rata == Decimal("400.00")
        assert dossier.form_cqs.cellulare == "+393331234567"

    def test_generic_form_prefill(self):
        session = _make_session(extracted_data=[
            _make_ed("birthdate", "01/08/1985"),
            _make_ed("provincia_residenza", "TO"),
        ])
        dossier = build_dossier(session)
        assert dossier.form_generic is not None
        assert dossier.form_generic.provincia_residenza == "TO"


class TestCompleteness:
    """Test the completeness calculation."""

    def test_fully_complete(self):
        ana = DossierAnagrafica(
            nome="Mario", cognome="Rossi", codice_fiscale="RSSMRA85M01H501Z",
            data_nascita="01/08/1985", eta=40, telefono="+39333",
        )
        lavoro = DossierLavoro(tipo_impiego="dipendente", reddito_netto_mensile=Decimal("2000"))
        assert _calculate_completeness(ana, lavoro) == 1.0

    def test_partially_complete(self):
        ana = DossierAnagrafica(nome="Mario", cognome="Rossi")
        lavoro = DossierLavoro()
        result = _calculate_completeness(ana, lavoro)
        assert 0.0 < result < 1.0

    def test_empty(self):
        assert _calculate_completeness(DossierAnagrafica(), DossierLavoro()) == 0.0


class TestConfidence:
    """Test the confidence calculation."""

    def test_with_data(self):
        session = _make_session(extracted_data=[
            _make_ed("age", "40", confidence=1.0),
            _make_ed("net_salary", "2000", confidence=0.85),
            _make_ed("employer_name", "ACME", confidence=0.50),
        ])
        avg, low = _calculate_confidence(session)
        assert avg == pytest.approx(0.78, abs=0.01)
        assert "employer_name" in low

    def test_empty(self):
        session = _make_session()
        avg, low = _calculate_confidence(session)
        assert avg == 0.0
        assert low == []


class TestFormatTelegram:
    """Test Telegram message formatting."""

    def test_basic_format(self):
        session = _make_session(extracted_data=[
            _make_ed("codice_fiscale", "RSSMRA85M01H501Z"),
            _make_ed("age", "40", confidence=1.0),
            _make_ed("net_salary", "2000.00", confidence=0.85),
        ])
        dossier = build_dossier(session)
        text = format_dossier_telegram(dossier)
        assert "DOSSIER" in text
        assert "ANAGRAFICA" in text
        assert "Mario" in text
        assert "Rossi" in text

    def test_with_products(self):
        pm = MagicMock()
        pm.product_name = "CdQ Statale"
        pm.sub_type = None
        pm.eligible = True
        pm.rank = 1

        session = _make_session(product_matches=[pm])
        dossier = build_dossier(session)
        text = format_dossier_telegram(dossier)
        assert "CdQ Statale" in text
        assert "PRODOTTI" in text
