"""Product type definitions and sub-type mappings for Primo Network products."""

from __future__ import annotations

from enum import StrEnum

from src.models.enums import EmployerCategory, PensionSource


class ProductType(StrEnum):
    """The 9 financial products evaluated by the eligibility engine."""

    CDQ_STIPENDIO = "cdq_stipendio"
    CDQ_PENSIONE = "cdq_pensione"
    DELEGA = "delega"
    PRESTITO_PERSONALE = "prestito_personale"
    MUTUO_ACQUISTO = "mutuo_acquisto"
    MUTUO_SURROGA = "mutuo_surroga"
    MUTUO_CONSOLIDAMENTO = "mutuo_consolidamento"
    ANTICIPO_TFS = "anticipo_tfs"
    CREDITO_ASSICURATIVO = "credito_assicurativo"


# Italian display names per employer category (CdQ Stipendio & Delega)
CDQ_STIPENDIO_SUBTYPES: dict[EmployerCategory, str] = {
    EmployerCategory.STATALE: "Dipendente Statale",
    EmployerCategory.PUBBLICO: "Dipendente Pubblico",
    EmployerCategory.PRIVATO: "Dipendente Privato",
    EmployerCategory.PARAPUBBLICO: "Dipendente Parapubblico",
}

DELEGA_SUBTYPES: dict[EmployerCategory, str] = CDQ_STIPENDIO_SUBTYPES

# Italian display names per pension source (CdQ Pensione)
CDQ_PENSIONE_SUBTYPES: dict[PensionSource, str] = {
    PensionSource.INPS: "Pensionato INPS",
    PensionSource.INPDAP: "Pensionato INPDAP",
    PensionSource.ALTRO: "Pensionato Altro Ente",
}

# Italian display names for all products
PRODUCT_DISPLAY_NAMES: dict[ProductType, str] = {
    ProductType.CDQ_STIPENDIO: "Cessione del Quinto Stipendio",
    ProductType.CDQ_PENSIONE: "Cessione del Quinto Pensione",
    ProductType.DELEGA: "Delegazione di Pagamento",
    ProductType.PRESTITO_PERSONALE: "Prestito Personale",
    ProductType.MUTUO_ACQUISTO: "Mutuo Acquisto",
    ProductType.MUTUO_SURROGA: "Mutuo Surroga",
    ProductType.MUTUO_CONSOLIDAMENTO: "Mutuo Consolidamento Debiti",
    ProductType.ANTICIPO_TFS: "Anticipo TFS/TFR",
    ProductType.CREDITO_ASSICURATIVO: "Credito Assicurativo",
}
