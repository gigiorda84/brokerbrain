"""GDPR Art. 15 data export — builds a full personal data summary.

Shared by Telegram /i_miei_dati and WhatsApp "miei dati" keyword.
Returns formatted Italian text, split into chunks if exceeding Telegram's 4096-char limit.

Usage:
    from src.security.data_export import export_user_data

    chunks = await export_user_data(db, user)
    for chunk in chunks:
        await send(chunk)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.appointment import Appointment
from src.models.calculation import CdQCalculation, DTICalculation
from src.models.document import Document
from src.models.extracted_data import ExtractedData
from src.models.liability import Liability
from src.models.product_match import ProductMatch
from src.models.session import Session
from src.models.user import User
from src.security.consent import consent_manager
from src.security.encryption import field_encryptor

logger = logging.getLogger(__name__)

_MAX_CHUNK = 4000  # Leave margin under Telegram's 4096 limit


def _fmt_date(dt: Any) -> str:
    """Format a datetime as DD/MM/YYYY HH:MM or N/D."""
    if dt is None:
        return "N/D"
    try:
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)


def _fmt_decimal(val: Any) -> str:
    """Format a Decimal as Italian currency string."""
    if val is None:
        return "N/D"
    try:
        return f"\u20ac{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)


def _decrypt_value(ed: ExtractedData) -> str:
    """Safely decrypt an ExtractedData value."""
    if ed.value is None:
        return "N/D"
    if ed.value_encrypted:
        try:
            return field_encryptor.decrypt(ed.value)
        except Exception:
            return "[crittografato]"
    return ed.value


def _split_text(text: str, max_len: int = _MAX_CHUNK) -> list[str]:
    """Split text into chunks at line boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = current + line + "\n" if current else line + "\n"
        if len(candidate) > max_len and current:
            chunks.append(current.rstrip("\n"))
            current = line + "\n"
        else:
            current = candidate

    if current.strip():
        chunks.append(current.rstrip("\n"))

    return chunks


async def export_user_data(db: AsyncSession, user: User) -> list[str]:
    """Build a comprehensive GDPR data export for the user.

    Returns a list of text chunks (usually 1, split if >4000 chars).
    """
    parts: list[str] = []

    # ── 1. Profile ────────────────────────────────────────────────
    reg_date = _fmt_date(user.created_at)
    parts.append(
        "I suoi dati presso ameconviene.it\n"
        "================================\n\n"
        "PROFILO\n"
        f"  Nome: {user.first_name or 'N/D'} {user.last_name or ''}\n"
        f"  Email: {user.email or 'N/D'}\n"
        f"  Canale: {user.channel}\n"
        f"  Registrazione: {reg_date}\n"
    )

    # ── 2. Sessions with related data ─────────────────────────────
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user.id)
        .options(
            selectinload(Session.extracted_data),
            selectinload(Session.documents),
            selectinload(Session.liabilities),
            selectinload(Session.dti_calculations),
            selectinload(Session.cdq_calculations),
            selectinload(Session.product_matches),
            selectinload(Session.appointments),
        )
        .order_by(Session.created_at.desc())
    )
    sessions = result.scalars().all()

    if not sessions:
        parts.append("\nNessuna sessione registrata.\n")
    else:
        parts.append(f"\nSESSIONI ({len(sessions)})\n")

        for i, s in enumerate(sessions, 1):
            parts.append(
                f"\n--- Sessione {i} ---\n"
                f"  Stato: {s.current_state}\n"
                f"  Esito: {s.outcome or 'in corso'}\n"
                f"  Inizio: {_fmt_date(s.started_at)}\n"
                f"  Fine: {_fmt_date(s.completed_at)}\n"
                f"  Messaggi: {s.message_count}\n"
            )

            # Extracted data
            if s.extracted_data:
                parts.append("  Dati estratti:\n")
                for ed in s.extracted_data:
                    val = _decrypt_value(ed)
                    parts.append(f"    - {ed.field_name}: {val} (fonte: {ed.source})\n")

            # Documents (metadata only, no content)
            if s.documents:
                parts.append("  Documenti:\n")
                for doc in s.documents:
                    conf = f"{doc.overall_confidence:.0%}" if doc.overall_confidence else "N/D"
                    parts.append(
                        f"    - {doc.doc_type or 'N/D'}: {doc.original_filename or 'N/D'} "
                        f"(confidenza: {conf})\n"
                    )

            # Liabilities
            if s.liabilities:
                parts.append("  Debiti/obbligazioni:\n")
                for li in s.liabilities:
                    parts.append(
                        f"    - {li.type}: rata {_fmt_decimal(li.monthly_installment)}"
                        f", creditore: {li.lender or 'N/D'}\n"
                    )

            # DTI calculations
            if s.dti_calculations:
                parts.append("  Calcoli DTI:\n")
                for dti in s.dti_calculations:
                    parts.append(
                        f"    - Reddito: {_fmt_decimal(dti.monthly_income)}"
                        f", DTI attuale: {dti.current_dti:.1%}\n"
                    )

            # CdQ calculations
            if s.cdq_calculations:
                parts.append("  Calcoli CdQ:\n")
                for cdq in s.cdq_calculations:
                    parts.append(
                        f"    - Reddito netto: {_fmt_decimal(cdq.net_income)}"
                        f", rata CdQ disponibile: {_fmt_decimal(cdq.available_cdq)}\n"
                    )

            # Product matches
            if s.product_matches:
                parts.append("  Prodotti verificati:\n")
                for pm in s.product_matches:
                    status = "idoneo" if pm.eligible else "non idoneo"
                    parts.append(f"    - {pm.product_name}: {status}\n")

            # Appointments
            if s.appointments:
                parts.append("  Appuntamenti:\n")
                for apt in s.appointments:
                    parts.append(
                        f"    - {_fmt_date(apt.scheduled_at)}: {apt.status}\n"
                    )

    # ── 3. Consent history ────────────────────────────────────────
    consent_history = await consent_manager.export_consent_history(db, user.id)
    if consent_history:
        parts.append("\nSTORICO CONSENSI\n")
        for c in consent_history:
            status = "concesso" if c["granted"] else "revocato"
            parts.append(
                f"  - {c['consent_type']}: {status} ({c['method']}, {c['timestamp'] or 'N/D'})\n"
            )

    # ── Footer ────────────────────────────────────────────────────
    parts.append(
        "\n"
        "Per richiedere la cancellazione: /elimina_dati\n"
        "Per assistenza: privacy@primonetwork.it"
    )

    full_text = "".join(parts)
    return _split_text(full_text)
