"""Queue committed consent decisions for mapped products.

Revision ID: 20261031_85
Revises: 20261031_84
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_85"
down_revision = "20261031_84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_consent_product_sync_sequences",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_product", sa.String(length=80), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name="ck_crm_consent_sync_sequence_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_consent_sync_sequence_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "recipient_product"),
    )
    op.create_table(
        "crm_consent_product_sync_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_product", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("consent_event_id", sa.BigInteger(), nullable=False),
        sa.Column("external_customer_id", sa.String(length=200), nullable=False),
        sa.Column("purpose_key", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_product", sa.String(length=80), nullable=True),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(recipient_product)) BETWEEN 2 AND 80",
            name="ck_crm_consent_sync_outbox_product",
        ),
        sa.CheckConstraint(
            "length(trim(external_customer_id)) BETWEEN 1 AND 200",
            name="ck_crm_consent_sync_outbox_external_id",
        ),
        sa.CheckConstraint(
            "decision IN ('granted', 'withdrawn')",
            name="ck_crm_consent_sync_outbox_decision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_consent_sync_outbox_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["consent_event_id"],
            ["crm_communication_consent_events.id"],
            name="fk_crm_consent_sync_outbox_event",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "recipient_product",
            "sequence",
            name="uq_crm_consent_sync_outbox_sequence",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "recipient_product",
            "consent_event_id",
            name="uq_crm_consent_sync_outbox_event",
        ),
    )
    op.create_index(
        "ix_crm_consent_sync_outbox_recipient_cursor",
        "crm_consent_product_sync_outbox",
        ["tenant_id", "recipient_product", "sequence"],
    )
    for table in ("crm_consent_product_sync_sequences", "crm_consent_product_sync_outbox"):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
        )
    op.execute(
        """
        CREATE FUNCTION protect_crm_consent_product_sync_outbox()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $outbox$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'CRM consent product sync outbox is append-only'
                USING ERRCODE = '55000';
        END;
        $outbox$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_crm_consent_product_sync_outbox_append_only
        BEFORE UPDATE OR DELETE ON crm_consent_product_sync_outbox
        FOR EACH ROW EXECUTE FUNCTION protect_crm_consent_product_sync_outbox()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_crm_consent_product_sync_outbox_append_only "
        "ON crm_consent_product_sync_outbox"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_crm_consent_product_sync_outbox()")
    op.drop_index(
        "ix_crm_consent_sync_outbox_recipient_cursor",
        table_name="crm_consent_product_sync_outbox",
    )
    op.drop_table("crm_consent_product_sync_outbox")
    op.drop_table("crm_consent_product_sync_sequences")
