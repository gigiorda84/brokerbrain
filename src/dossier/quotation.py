"""Quotation form persistence — saves pre-filled form data to QuotationData table.

After the dossier is built, this module persists the form fields so they
can be retrieved later by the admin dashboard or API export.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.events import emit
from src.models.enums import QuotationFormType
from src.models.quotation import QuotationData
from src.schemas.dossier import Dossier
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


async def persist_quotation_forms(db: AsyncSession, dossier: Dossier) -> list[QuotationData]:
    """Save the dossier's pre-filled form fields to the database.

    Creates one QuotationData row per form type (CQS, mutuo, generic).
    Only persists forms that have at least one non-None field.
    """
    rows: list[QuotationData] = []

    if dossier.form_cqs:
        fields = dossier.form_cqs.model_dump(exclude_none=True)
        if fields:
            row = QuotationData(
                session_id=dossier.session_id,
                form_type=QuotationFormType.CQS.value,
                form_fields=fields,
            )
            db.add(row)
            rows.append(row)

    if dossier.form_mutuo:
        fields = dossier.form_mutuo.model_dump(exclude_none=True)
        if fields:
            row = QuotationData(
                session_id=dossier.session_id,
                form_type=QuotationFormType.MUTUO.value,
                form_fields=fields,
            )
            db.add(row)
            rows.append(row)

    if dossier.form_generic:
        fields = dossier.form_generic.model_dump(exclude_none=True)
        if fields:
            row = QuotationData(
                session_id=dossier.session_id,
                form_type=QuotationFormType.GENERIC.value,
                form_fields=fields,
            )
            db.add(row)
            rows.append(row)

    if rows:
        await emit(SystemEvent(
            event_type=EventType.DOSSIER_GENERATED,
            session_id=dossier.session_id,
            data={
                "form_types": [r.form_type for r in rows],
                "completeness": dossier.completeness,
                "avg_confidence": dossier.avg_confidence,
            },
            source_module="dossier.quotation",
        ))

    return rows
