"""Pydantic schemas for the lead dossier and quotation form pre-fill.

Dossier = full lead package assembled from a completed session.
Quotation forms = the 3 Primo Network form types (CQS, mutuo, generic).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# ── Quotation form schemas (Section 21.3 of PRD) ──────────────────────


class CQSFormFields(BaseModel):
    """Fields for Primo Network CQS/Delega calculator form."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_nascita: str | None = None  # DD/MM/YYYY
    prodotto: str | None = None
    rata: Decimal | None = None
    durata: int | None = None  # months
    data_assunzione: str | None = None  # DD/MM/YYYY
    nome: str | None = None
    cognome: str | None = None
    email: str | None = None
    cellulare: str | None = None


class MutuoFormFields(BaseModel):
    """Fields for Primo Network mutuo calculator form."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    prodotto: str | None = None
    durata: int | None = None
    cadenza: str | None = None  # mensile
    importo: Decimal | None = None
    prima_casa: bool | None = None
    prezzo_acquisto: Decimal | None = None
    provincia_immobile: str | None = None
    reddito_netto: Decimal | None = None
    rata_debiti: Decimal | None = None
    nucleo_familiare: int | None = None
    percettori_reddito: int | None = None
    data_nascita: str | None = None
    data_assunzione: str | None = None
    nome: str | None = None
    cognome: str | None = None
    email: str | None = None
    cellulare: str | None = None


class GenericFormFields(BaseModel):
    """Fields for Primo Network generic quote form."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    importo: Decimal | None = None
    prodotto: str | None = None
    provincia_residenza: str | None = None
    data_nascita: str | None = None
    nome: str | None = None
    cognome: str | None = None
    email: str | None = None
    cellulare: str | None = None


# ── Dossier sub-sections ──────────────────────────────────────────────


class FieldWithSource(BaseModel):
    """A data field with its provenance for the dossier."""

    field_name: str
    value: str | None = None
    source: str | None = None
    confidence: float | None = None


class DossierAnagrafica(BaseModel):
    """Personal data section."""

    nome: str | None = None
    cognome: str | None = None
    codice_fiscale: str | None = None
    data_nascita: str | None = None
    eta: int | None = None
    genere: str | None = None
    luogo_nascita: str | None = None
    telefono: str | None = None
    email: str | None = None


class DossierLavoro(BaseModel):
    """Employment/income section."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tipo_impiego: str | None = None
    categoria_datore: str | None = None
    fonte_pensione: str | None = None
    reddito_netto_mensile: Decimal | None = None
    data_assunzione: str | None = None


class DossierNucleoFamiliare(BaseModel):
    """Household section."""

    componenti: int | None = None
    percettori_reddito: int | None = None


class DossierLiability(BaseModel):
    """A single existing financial obligation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tipo: str
    rata_mensile: Decimal | None = None
    mesi_residui: int | None = None
    debito_residuo: Decimal | None = None
    finanziatore: str | None = None
    rinnovabile: bool | None = None


class DossierCalcoli(BaseModel):
    """Calculation results section."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dti_corrente: Decimal | None = None
    dti_proiettato: Decimal | None = None
    cdq_rata_disponibile: Decimal | None = None
    delega_rata_disponibile: Decimal | None = None


class DossierProduct(BaseModel):
    """A matched product for the dossier."""

    prodotto: str
    sotto_tipo: str | None = None
    idoneo: bool
    motivazione: str | None = None
    rank: int | None = None


class DossierDocument(BaseModel):
    """An attached document reference."""

    tipo: str | None = None
    filename: str | None = None
    confidenza: float | None = None
    elaborato_con: str | None = None


# ── Full dossier ──────────────────────────────────────────────────────


class Dossier(BaseModel):
    """Complete lead dossier assembled from a finished session.

    Sections:
    1. Anagrafica (personal data)
    2. Lavoro (employment/income)
    3. Nucleo familiare (household)
    4. Impegni finanziari (liabilities)
    5. Calcoli (DTI, CdQ)
    6. Prodotti compatibili (matched products)
    7. Documenti allegati (document references)
    8. Campi pre-compilati (quotation form fields)
    9. Metadata (confidence, completeness)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Identity
    session_id: str
    user_channel: str | None = None
    created_at: datetime | None = None

    # Sections
    anagrafica: DossierAnagrafica = DossierAnagrafica()
    lavoro: DossierLavoro = DossierLavoro()
    nucleo_familiare: DossierNucleoFamiliare = DossierNucleoFamiliare()
    impegni: list[DossierLiability] = []
    calcoli: DossierCalcoli = DossierCalcoli()
    prodotti: list[DossierProduct] = []
    documenti: list[DossierDocument] = []

    # Pre-filled form fields (keyed by form type)
    form_cqs: CQSFormFields | None = None
    form_mutuo: MutuoFormFields | None = None
    form_generic: GenericFormFields | None = None

    # Field-level provenance
    field_sources: list[FieldWithSource] = []

    # Quality metrics
    completeness: float = 0.0  # 0.0–1.0
    avg_confidence: float = 0.0
    low_confidence_fields: list[str] = []
