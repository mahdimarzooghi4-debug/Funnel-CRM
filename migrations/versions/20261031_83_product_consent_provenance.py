"""Record provenance and event idempotency for product-reported consent.

Revision ID: 20261031_83
Revises: 20261031_82
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_83"
down_revision = "20261031_82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_communication_consent_events",
        sa.Column("source_product", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "crm_communication_consent_events",
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_consent_source_pair",
        "crm_communication_consent_events",
        "(source_product IS NULL) = (source_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_crm_consent_source_product",
        "crm_communication_consent_events",
        "source_product IS NULL OR source_product ~ '^[a-z0-9][a-z0-9._-]{1,79}$'",
    )
    op.create_index(
        "uq_crm_consent_source_event",
        "crm_communication_consent_events",
        ["tenant_id", "source_product", "source_event_id"],
        unique=True,
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_crm_consent_source_event",
        table_name="crm_communication_consent_events",
    )
    op.drop_constraint(
        "ck_crm_consent_source_product",
        "crm_communication_consent_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_crm_consent_source_pair",
        "crm_communication_consent_events",
        type_="check",
    )
    op.drop_column("crm_communication_consent_events", "source_event_id")
    op.drop_column("crm_communication_consent_events", "source_product")
