"""Dossier builder — assembles a complete lead dossier from a finished session.

Pulls data from:
- Session model (FSM state, employment classification)
- ExtractedData rows (field-level data with source tracking)
- Liability rows (existing debts)
- DTI/CdQ calculations
- ProductMatch rows (eligibility results)
- Document rows (OCR metadata)
- User model (contact info)

Encrypted fields are decrypted on read via the field encryptor.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.session import Session as SessionModel
from src.schemas.dossier import (
    CQSFormFields,
    Dossier,
    DossierAnagrafica,
    DossierCalcoli,
    DossierDocument,
    DossierLavoro,
    DossierLiability,
    DossierNucleoFamiliare,
    DossierProduct,
    FieldWithSource,
    GenericFormFields,
    MutuoFormFields,
)
from src.security.encryption import field_encryptor

logger = logging.getLogger(__name__)

# Fields required for completeness calculation
REQUIRED_FIELDS: frozenset[str] = frozenset({
    "nome",
    "cognome",
    "codice_fiscale",
    "data_nascita",
    "age",
    "telefono",
    "tipo_impiego",
    "reddito_netto_mensile",
})

CONFIDENCE_THRESHOLD = 0.70


def build_dossier(session: SessionModel) -> Dossier:
    """Build a Dossier from a fully-loaded session (with relationships).

    The session must have its relationships loaded (user, extracted_data,
    liabilities, dti_calculations, cdq_calculations, product_matches,
    documents). Use `load_session_for_dossier()` to fetch with eager loading.
    """
    extracted = _build_field_map(session)
    user = session.user

    anagrafica = _build_anagrafica(extracted, user)
    lavoro = _build_lavoro(extracted, session)
    nucleo = _build_nucleo(extracted)
    impegni = _build_impegni(session)
    calcoli = _build_calcoli(session)
    prodotti = _build_prodotti(session)
    documenti = _build_documenti(session)
    field_sources = _build_field_sources(session)

    # Pre-fill quotation forms
    form_cqs = _build_cqs_form(anagrafica, lavoro, extracted, calcoli)
    form_mutuo = _build_mutuo_form(anagrafica, lavoro, nucleo, extracted, calcoli)
    form_generic = _build_generic_form(anagrafica, extracted)

    # Quality metrics
    completeness = _calculate_completeness(anagrafica, lavoro)
    avg_confidence, low_fields = _calculate_confidence(session)

    return Dossier(
        session_id=str(session.id),
        user_channel=user.channel if user else None,
        created_at=session.started_at,
        anagrafica=anagrafica,
        lavoro=lavoro,
        nucleo_familiare=nucleo,
        impegni=impegni,
        calcoli=calcoli,
        prodotti=prodotti,
        documenti=documenti,
        form_cqs=form_cqs,
        form_mutuo=form_mutuo,
        form_generic=form_generic,
        field_sources=field_sources,
        completeness=completeness,
        avg_confidence=avg_confidence,
        low_confidence_fields=low_fields,
    )


async def load_session_for_dossier(db: AsyncSession, session_id: str) -> SessionModel | None:
    """Load a session with all relationships needed for dossier building."""
    from sqlalchemy import select

    from src.models.session import Session as SessionModel

    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.id == session_id)
        .options(
            selectinload(SessionModel.user),
            selectinload(SessionModel.extracted_data),
            selectinload(SessionModel.liabilities),
            selectinload(SessionModel.dti_calculations),
            selectinload(SessionModel.cdq_calculations),
            selectinload(SessionModel.product_matches),
            selectinload(SessionModel.documents),
            selectinload(SessionModel.messages),
        )
    )
    return result.scalar_one_or_none()


# ── Internal helpers ──────────────────────────────────────────────────


def _build_field_map(session: SessionModel) -> dict[str, str]:
    """Extract all fields into a plain dict, decrypting as needed."""
    fields: dict[str, str] = {}
    for ed in session.extracted_data:
        if ed.value is None:
            continue
        if ed.value_encrypted:
            try:
                fields[ed.field_name] = field_encryptor.decrypt(ed.value)
            except Exception:
                logger.warning("Failed to decrypt field %s", ed.field_name)
                continue
        else:
            fields[ed.field_name] = ed.value
    return fields


def _build_anagrafica(extracted: dict[str, str], user) -> DossierAnagrafica:
    """Build the personal data section."""
    return DossierAnagrafica(
        nome=extracted.get("nome") or (user.first_name if user else None),
        cognome=extracted.get("cognome") or (user.last_name if user else None),
        codice_fiscale=extracted.get("codice_fiscale"),
        data_nascita=extracted.get("birthdate") or extracted.get("data_nascita"),
        eta=_safe_int(extracted.get("age")),
        genere=extracted.get("gender"),
        luogo_nascita=extracted.get("birthplace"),
        telefono=extracted.get("phone_number") or (user.phone if user else None),
        email=extracted.get("email") or (user.email if user else None),
    )


def _build_lavoro(extracted: dict[str, str], session: SessionModel) -> DossierLavoro:
    """Build the employment/income section."""
    net_income = _safe_decimal(
        extracted.get("net_salary") or extracted.get("net_pension") or extracted.get("reddito_imponibile")
    )
    return DossierLavoro(
        tipo_impiego=session.employment_type,
        categoria_datore=session.employer_category,
        fonte_pensione=session.pension_source,
        reddito_netto_mensile=net_income,
        data_assunzione=extracted.get("data_assunzione") or extracted.get("hire_date"),
    )


def _build_nucleo(extracted: dict[str, str]) -> DossierNucleoFamiliare:
    """Build the household section."""
    return DossierNucleoFamiliare(
        componenti=_safe_int(extracted.get("nucleo_familiare") or extracted.get("household_members")),
        percettori_reddito=_safe_int(extracted.get("percettori_reddito") or extracted.get("income_earners")),
    )


def _build_impegni(session: SessionModel) -> list[DossierLiability]:
    """Build the liabilities section."""
    return [
        DossierLiability(
            tipo=lib.type,
            rata_mensile=lib.monthly_installment,
            mesi_residui=lib.remaining_months,
            debito_residuo=lib.residual_amount,
            finanziatore=lib.lender,
            rinnovabile=lib.renewable,
        )
        for lib in session.liabilities
    ]


def _build_calcoli(session: SessionModel) -> DossierCalcoli:
    """Build the calculations section from most recent DTI/CdQ."""
    calcoli = DossierCalcoli()
    if session.dti_calculations:
        latest_dti = session.dti_calculations[-1]
        calcoli.dti_corrente = latest_dti.current_dti
        calcoli.dti_proiettato = latest_dti.projected_dti
    if session.cdq_calculations:
        latest_cdq = session.cdq_calculations[-1]
        calcoli.cdq_rata_disponibile = latest_cdq.available_cdq
        calcoli.delega_rata_disponibile = latest_cdq.available_delega
    return calcoli


def _build_prodotti(session: SessionModel) -> list[DossierProduct]:
    """Build the matched products section."""
    return [
        DossierProduct(
            prodotto=pm.product_name,
            sotto_tipo=pm.sub_type,
            idoneo=pm.eligible,
            motivazione=None,
            rank=pm.rank,
        )
        for pm in sorted(session.product_matches, key=lambda p: (not p.eligible, p.rank or 999))
    ]


def _build_documenti(session: SessionModel) -> list[DossierDocument]:
    """Build the documents section."""
    return [
        DossierDocument(
            tipo=doc.doc_type,
            filename=doc.original_filename,
            confidenza=doc.overall_confidence,
            elaborato_con=doc.processing_model,
        )
        for doc in session.documents
    ]


def _build_field_sources(session: SessionModel) -> list[FieldWithSource]:
    """Build the provenance list for all extracted fields."""
    sources = []
    for ed in session.extracted_data:
        val = ed.value
        if ed.value_encrypted and val:
            val = "***"  # Don't expose encrypted values in source listing
        sources.append(FieldWithSource(
            field_name=ed.field_name,
            value=val,
            source=ed.source,
            confidence=ed.confidence,
        ))
    return sources


# ── Quotation form pre-fill ───────────────────────────────────────────


def _build_cqs_form(
    ana: DossierAnagrafica,
    lavoro: DossierLavoro,
    extracted: dict[str, str],
    calcoli: DossierCalcoli,
) -> CQSFormFields:
    """Pre-fill the CQS/Delega calculator form."""
    return CQSFormFields(
        data_nascita=ana.data_nascita,
        prodotto=extracted.get("prodotto_cqs") or "Cessione del Quinto",
        rata=calcoli.cdq_rata_disponibile,
        durata=_safe_int(extracted.get("durata_cqs")),
        data_assunzione=lavoro.data_assunzione,
        nome=ana.nome,
        cognome=ana.cognome,
        email=ana.email,
        cellulare=ana.telefono,
    )


def _build_mutuo_form(
    ana: DossierAnagrafica,
    lavoro: DossierLavoro,
    nucleo: DossierNucleoFamiliare,
    extracted: dict[str, str],
    calcoli: DossierCalcoli,
) -> MutuoFormFields:
    """Pre-fill the mutuo calculator form."""
    total_obligations = Decimal("0")
    if calcoli.dti_corrente and lavoro.reddito_netto_mensile:
        total_obligations = calcoli.dti_corrente * lavoro.reddito_netto_mensile

    return MutuoFormFields(
        prodotto=extracted.get("prodotto_mutuo") or "Mutuo",
        durata=_safe_int(extracted.get("durata_mutuo")),
        cadenza="mensile",
        importo=_safe_decimal(extracted.get("importo_mutuo")),
        prima_casa=extracted.get("prima_casa", "").lower() in ("si", "sì", "true", "1"),
        prezzo_acquisto=_safe_decimal(extracted.get("prezzo_acquisto")),
        provincia_immobile=extracted.get("provincia_immobile"),
        reddito_netto=lavoro.reddito_netto_mensile,
        rata_debiti=total_obligations if total_obligations > 0 else None,
        nucleo_familiare=nucleo.componenti,
        percettori_reddito=nucleo.percettori_reddito,
        data_nascita=ana.data_nascita,
        data_assunzione=lavoro.data_assunzione,
        nome=ana.nome,
        cognome=ana.cognome,
        email=ana.email,
        cellulare=ana.telefono,
    )


def _build_generic_form(ana: DossierAnagrafica, extracted: dict[str, str]) -> GenericFormFields:
    """Pre-fill the generic quote form."""
    return GenericFormFields(
        importo=_safe_decimal(extracted.get("importo_richiesto")),
        prodotto=extracted.get("prodotto"),
        provincia_residenza=extracted.get("provincia_residenza"),
        data_nascita=ana.data_nascita,
        nome=ana.nome,
        cognome=ana.cognome,
        email=ana.email,
        cellulare=ana.telefono,
    )


# ── Quality metrics ──────────────────────────────────────────────────


def _calculate_completeness(ana: DossierAnagrafica, lavoro: DossierLavoro) -> float:
    """Calculate dossier completeness as ratio of filled required fields."""
    filled = 0
    total = len(REQUIRED_FIELDS)
    field_values = {
        "nome": ana.nome,
        "cognome": ana.cognome,
        "codice_fiscale": ana.codice_fiscale,
        "data_nascita": ana.data_nascita,
        "age": ana.eta,
        "telefono": ana.telefono,
        "tipo_impiego": lavoro.tipo_impiego,
        "reddito_netto_mensile": lavoro.reddito_netto_mensile,
    }
    for field in REQUIRED_FIELDS:
        if field_values.get(field) is not None:
            filled += 1
    return round(filled / total, 2) if total > 0 else 0.0


def _calculate_confidence(session: SessionModel) -> tuple[float, list[str]]:
    """Calculate average confidence and identify low-confidence fields."""
    confidences = []
    low_fields = []
    for ed in session.extracted_data:
        if ed.confidence is not None:
            confidences.append(ed.confidence)
            if ed.confidence < CONFIDENCE_THRESHOLD:
                low_fields.append(ed.field_name)
    avg = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    return avg, low_fields


# ── Formatting helpers ────────────────────────────────────────────────


def format_dossier_telegram(dossier: Dossier) -> str:
    """Format a dossier as a Telegram-friendly text message for admin /dossier command."""
    lines = [f"📋 DOSSIER — Sessione {dossier.session_id[:8]}"]
    lines.append(f"Completezza: {dossier.completeness:.0%} | Confidenza media: {dossier.avg_confidence:.0%}")
    lines.append("")

    # Anagrafica
    a = dossier.anagrafica
    lines.append("👤 ANAGRAFICA")
    if a.nome or a.cognome:
        lines.append(f"  Nome: {a.nome or ''} {a.cognome or ''}")
    if a.codice_fiscale:
        lines.append(f"  CF: {a.codice_fiscale}")
    if a.data_nascita:
        lines.append(f"  Nascita: {a.data_nascita}")
    if a.eta:
        lines.append(f"  Età: {a.eta}")
    if a.telefono:
        lines.append(f"  Tel: {a.telefono}")
    lines.append("")

    # Lavoro
    lav = dossier.lavoro
    lines.append("💼 SITUAZIONE LAVORATIVA")
    if lav.tipo_impiego:
        lines.append(f"  Tipo: {lav.tipo_impiego}")
    if lav.categoria_datore:
        lines.append(f"  Datore: {lav.categoria_datore}")
    if lav.reddito_netto_mensile:
        lines.append(f"  Reddito netto: €{lav.reddito_netto_mensile:,.2f}")
    lines.append("")

    # Impegni
    if dossier.impegni:
        lines.append("💳 IMPEGNI FINANZIARI")
        for imp in dossier.impegni:
            rata = f"€{imp.rata_mensile:,.2f}" if imp.rata_mensile else "n/d"
            lines.append(f"  • {imp.tipo}: {rata}/mese")
        lines.append("")

    # Calcoli
    c = dossier.calcoli
    if c.dti_corrente is not None or c.cdq_rata_disponibile is not None:
        lines.append("📊 CALCOLI")
        if c.dti_corrente is not None:
            lines.append(f"  DTI: {c.dti_corrente:.1%}")
        if c.cdq_rata_disponibile is not None:
            lines.append(f"  CdQ disponibile: €{c.cdq_rata_disponibile:,.2f}/mese")
        if c.delega_rata_disponibile is not None:
            lines.append(f"  Delega disponibile: €{c.delega_rata_disponibile:,.2f}/mese")
        lines.append("")

    # Prodotti
    if dossier.prodotti:
        lines.append("✅ PRODOTTI COMPATIBILI")
        for p in dossier.prodotti:
            icon = "✅" if p.idoneo else "❌"
            lines.append(f"  {icon} {p.prodotto}")
        lines.append("")

    # Warnings
    if dossier.low_confidence_fields:
        lines.append(f"⚠️ Campi bassa confidenza: {', '.join(dossier.low_confidence_fields)}")

    return "\n".join(lines)


# ── Safe type conversion ─────────────────────────────────────────────


def _safe_int(value: str | None) -> int | None:
    """Safely convert a string to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _safe_decimal(value: str | None) -> Decimal | None:
    """Safely convert a string to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None
