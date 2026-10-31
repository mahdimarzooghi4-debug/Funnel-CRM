"""Preserve the source decision time for consent eligibility ordering.

Revision ID: 20261031_84
Revises: 20261031_83
"""

from alembic import op
import sqlalchemy as sa

revision = "20261031_84"
down_revision = "20261031_83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_communication_consent_events",
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE crm_communication_consent_events "
        "SET decision_at = recorded_at WHERE decision_at IS NULL"
    )
    op.alter_column(
        "crm_communication_consent_events",
        "decision_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    )
    op.drop_index(
        "ix_crm_consent_latest_by_scope",
        table_name="crm_communication_consent_events",
    )
    op.create_index(
        "ix_crm_consent_latest_by_decision_time",
        "crm_communication_consent_events",
        [
            "tenant_id",
            "profile_id",
            "purpose_key",
            "channel",
            "decision_at",
            "recorded_at",
            "id",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_consent_latest_by_decision_time",
        table_name="crm_communication_consent_events",
    )
    op.create_index(
        "ix_crm_consent_latest_by_scope",
        "crm_communication_consent_events",
        [
            "tenant_id",
            "profile_id",
            "purpose_key",
            "channel",
            "recorded_at",
            "id",
        ],
    )
    op.drop_column("crm_communication_consent_events", "decision_at")
