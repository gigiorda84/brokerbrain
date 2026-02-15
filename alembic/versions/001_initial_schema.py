"""Initial schema — all 16 tables.

Revision ID: 001
Revises: None
Create Date: 2026-02-15
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # ── Standalone tables (no FKs) ─────────────────────────────────────

    op.create_table(
        "admin_access",
        sa.Column("admin_id", sa.String(100), nullable=False, index=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_entity", sa.String(50), comment="Table/model name"),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("details", sa.String(1000)),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_log",
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), index=True),
        sa.Column("actor_id", sa.String(100), comment="User ID, admin ID, or 'system'"),
        sa.Column("actor_role", sa.String(50), comment="user, admin, system, bot"),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "operators",
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("calendar_id", sa.String(255), comment="Cal.com calendar ID"),
        sa.Column("specializations", postgresql.ARRAY(sa.String(50)), comment="Product types this operator handles"),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "users",
        sa.Column("phone", sa.String(20)),
        sa.Column("telegram_id", sa.String(50)),
        sa.Column("whatsapp_id", sa.String(50)),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("email", sa.String(255)),
        sa.Column("codice_fiscale_encrypted", sa.Text(), comment="AES-256-GCM encrypted"),
        sa.Column("consent_status", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("anonymized", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_whatsapp_id", "users", ["whatsapp_id"], unique=True)
    op.create_index("ix_users_anonymized", "users", ["anonymized"])

    # ── Tables with FK to users ────────────────────────────────────────

    op.create_table(
        "consent_records",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("consent_type", sa.String(50), nullable=False, comment="ConsentType enum value"),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("method", sa.String(50), nullable=False, comment="How consent was given: chat, link, form"),
        sa.Column("message_text", sa.String(500)),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "data_deletion_requests",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("admin_notified", sa.Boolean(), nullable=False),
        sa.Column("admin_notes", sa.String(1000)),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "sessions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("current_state", sa.String(50), nullable=False),
        sa.Column("employment_type", sa.String(30)),
        sa.Column("employer_category", sa.String(30)),
        sa.Column("pension_source", sa.String(20)),
        sa.Column("track_type", sa.String(20), comment="ocr or manual"),
        sa.Column("income_doc_type", sa.String(50)),
        sa.Column("outcome", sa.String(30)),
        sa.Column("outcome_reason", sa.String(255)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Tables with FK to sessions ─────────────────────────────────────

    op.create_table(
        "appointments",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operators.id")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cal_event_id", sa.String(255), comment="Cal.com / Calendly event ID"),
        sa.Column("notes", sa.String(1000)),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cdq_calculations",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("net_income", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_cdq_rata", sa.Numeric(12, 2), nullable=False),
        sa.Column("existing_cdq", sa.Numeric(12, 2), nullable=False),
        sa.Column("available_cdq", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_delega_rata", sa.Numeric(12, 2), nullable=False),
        sa.Column("existing_delega", sa.Numeric(12, 2), nullable=False),
        sa.Column("available_delega", sa.Numeric(12, 2), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "documents",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("doc_type", sa.String(50), comment="Classified document type"),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("file_path_encrypted", sa.Text(), comment="AES-256-GCM encrypted file path"),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("file_size_bytes", sa.Integer()),
        sa.Column("ocr_result", postgresql.JSONB(astext_type=sa.Text()), comment="Full OCR extraction output"),
        sa.Column(
            "confidence_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            comment="Per-field confidence scores from OCR",
        ),
        sa.Column("overall_confidence", sa.Float()),
        sa.Column("processing_model", sa.String(50), comment="Which LLM model processed this"),
        sa.Column("processing_time_ms", sa.Integer(), comment="OCR processing time in milliseconds"),
        sa.Column("expires_at", sa.DateTime(timezone=True), comment="Auto-delete after retention period"),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "dti_calculations",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("monthly_income", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_obligations", sa.Numeric(12, 2), nullable=False),
        sa.Column("proposed_installment", sa.Numeric(12, 2)),
        sa.Column("current_dti", sa.Numeric(5, 4), nullable=False, comment="As decimal, e.g. 0.3500"),
        sa.Column("projected_dti", sa.Numeric(5, 4), comment="DTI including proposed installment"),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("role", sa.String(20), nullable=False, comment="user, assistant, or system"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("media_url", sa.Text(), comment="URL to attached media (image/document)"),
        sa.Column("media_type", sa.String(50), comment="MIME type of attached media"),
        sa.Column("state_at_send", sa.String(50)),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "product_matches",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("product_name", sa.String(100), nullable=False),
        sa.Column("sub_type", sa.String(100)),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), comment="Conditions met/unmet"),
        sa.Column("estimated_terms", postgresql.JSONB(astext_type=sa.Text()), comment="Estimated rates, amounts"),
        sa.Column("rank", sa.Integer(), comment="Display order, lower is better"),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "quotation_data",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("form_type", sa.String(20), nullable=False),
        sa.Column("form_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Tables with FK to sessions + documents ─────────────────────────

    op.create_table(
        "extracted_data",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("field_name", sa.String(100), nullable=False, index=True),
        sa.Column("value", sa.Text(), comment="Plain text or encrypted depending on field"),
        sa.Column("value_encrypted", sa.Boolean(), nullable=False, comment="Whether value is AES encrypted"),
        sa.Column("source", sa.String(30), nullable=False, comment="DataSource enum value"),
        sa.Column("confidence", sa.Float(), comment="0.0-1.0 confidence score"),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id")),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "liabilities",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True
        ),
        sa.Column("type", sa.String(50), nullable=False, comment="LiabilityType enum value"),
        sa.Column("monthly_installment", sa.Numeric(12, 2)),
        sa.Column("remaining_months", sa.Integer()),
        sa.Column("total_months", sa.Integer()),
        sa.Column("paid_months", sa.Integer()),
        sa.Column("residual_amount", sa.Numeric(12, 2)),
        sa.Column("lender", sa.String(200)),
        sa.Column("detected_from", sa.String(30), comment="DataSource enum value"),
        sa.Column("supporting_doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id")),
        sa.Column("renewable", sa.Boolean(), comment="Eligible for rinnovo CdQ"),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("liabilities")
    op.drop_table("extracted_data")
    op.drop_table("quotation_data")
    op.drop_table("product_matches")
    op.drop_table("messages")
    op.drop_table("dti_calculations")
    op.drop_table("documents")
    op.drop_table("cdq_calculations")
    op.drop_table("appointments")
    op.drop_table("sessions")
    op.drop_table("data_deletion_requests")
    op.drop_table("consent_records")
    op.drop_table("users")
    op.drop_table("operators")
    op.drop_table("audit_log")
    op.drop_table("admin_access")
