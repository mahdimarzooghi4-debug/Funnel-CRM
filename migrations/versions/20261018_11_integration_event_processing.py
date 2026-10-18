"""Add leases, bounded retries, and completion state to the product event inbox.

Revision ID: 20261018_11
Revises: 20261018_10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_11"
down_revision = "20261018_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_event_inbox",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "integration_event_inbox",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "integration_event_inbox",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "integration_event_inbox",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "integration_event_inbox",
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "integration_event_inbox",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Rows left in the pre-lease "processing" state have no safe owner token.
    # Return them to the queue so the new lease protocol can claim them cleanly.
    op.execute(
        """
        UPDATE integration_event_inbox
        SET processing_status = 'received',
            available_at = now(),
            last_error_code = 'recovered_pre_lease_state'
        WHERE processing_status = 'processing'
        """
    )
    op.create_check_constraint(
        "ck_integration_event_inbox_attempt_count",
        "integration_event_inbox",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_integration_event_inbox_lease_pair",
        "integration_event_inbox",
        "(lease_token IS NULL) = (lease_until IS NULL)",
    )
    op.create_check_constraint(
        "ck_integration_event_inbox_processing_lease",
        "integration_event_inbox",
        "processing_status <> 'processing' OR lease_token IS NOT NULL",
    )
    op.create_index(
        "ix_integration_event_inbox_available",
        "integration_event_inbox",
        ["tenant_id", "available_at", "received_at"],
        postgresql_where=sa.text("processing_status = 'received'"),
    )
    op.create_index(
        "ix_integration_event_inbox_expired_lease",
        "integration_event_inbox",
        ["tenant_id", "lease_until"],
        postgresql_where=sa.text("processing_status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_event_inbox_expired_lease",
        table_name="integration_event_inbox",
    )
    op.drop_index(
        "ix_integration_event_inbox_available",
        table_name="integration_event_inbox",
    )
    op.drop_constraint(
        "ck_integration_event_inbox_processing_lease",
        "integration_event_inbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_integration_event_inbox_lease_pair",
        "integration_event_inbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_integration_event_inbox_attempt_count",
        "integration_event_inbox",
        type_="check",
    )
    op.drop_column("integration_event_inbox", "processed_at")
    op.drop_column("integration_event_inbox", "last_error_code")
    op.drop_column("integration_event_inbox", "lease_until")
    op.drop_column("integration_event_inbox", "lease_token")
    op.drop_column("integration_event_inbox", "available_at")
    op.drop_column("integration_event_inbox", "attempt_count")
