"""Create a durable idempotent inbox for connected product events.

Revision ID: 20261018_10
Revises: 20261018_09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_10"
down_revision = "20261018_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_event_inbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_product", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("contract_name", sa.String(length=80), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_digest", sa.LargeBinary(), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            nullable=False,
            server_default="received",
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_integration_event_inbox_source",
        ),
        sa.CheckConstraint(
            "length(trim(event_type)) BETWEEN 3 AND 120",
            name="ck_integration_event_inbox_event_type",
        ),
        sa.CheckConstraint(
            "length(trim(contract_name)) BETWEEN 2 AND 80 AND contract_version > 0",
            name="ck_integration_event_inbox_contract",
        ),
        sa.CheckConstraint(
            "octet_length(event_digest) = 32",
            name="ck_integration_event_inbox_digest",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 131072",
            name="ck_integration_event_inbox_payload",
        ),
        sa.CheckConstraint(
            "processing_status IN ('received', 'processing', 'processed', 'failed')",
            name="ck_integration_event_inbox_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_integration_event_inbox_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_product",
            "event_id",
            name="uq_integration_event_inbox_idempotency",
        ),
    )
    op.create_index(
        "ix_integration_event_inbox_tenant_received",
        "integration_event_inbox",
        ["tenant_id", "received_at"],
    )
    op.create_index(
        "ix_integration_event_inbox_received_pending",
        "integration_event_inbox",
        ["received_at"],
        postgresql_where=sa.text("processing_status = 'received'"),
    )
    op.execute("ALTER TABLE integration_event_inbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE integration_event_inbox FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON integration_event_inbox
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE FUNCTION capture_integration_event_receipt_audit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            tenant_context_value uuid;
            connection_context_value uuid;
        BEGIN
            tenant_context_value := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
            connection_context_value :=
                NULLIF(current_setting('app.integration_connection_id', true), '')::uuid;
            IF tenant_context_value IS NULL OR tenant_context_value <> NEW.tenant_id THEN
                RAISE EXCEPTION 'verified tenant context is required for integration receipt'
                    USING ERRCODE = '42501';
            END IF;
            IF connection_context_value IS NULL OR connection_context_value <> NEW.connection_id THEN
                RAISE EXCEPTION 'verified product connection context is required for integration receipt'
                    USING ERRCODE = '42501';
            END IF;

            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                NEW.tenant_id, 'system', NULL, NULL,
                'integration.event.received', 'integration_event',
                NEW.source_product || ':' || NEW.event_id::text, NULL,
                NULL,
                jsonb_build_object(
                    'event_type', NEW.event_type,
                    'contract_name', NEW.contract_name,
                    'contract_version', NEW.contract_version,
                    'connection_id', NEW.connection_id
                ),
                NEW.correlation_id
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER integration_event_receipt_audit
        AFTER INSERT ON integration_event_inbox
        FOR EACH ROW EXECUTE FUNCTION capture_integration_event_receipt_audit()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER integration_event_receipt_audit ON integration_event_inbox")
    op.execute("DROP FUNCTION capture_integration_event_receipt_audit()")
    op.execute("DROP POLICY tenant_isolation ON integration_event_inbox")
    op.execute("ALTER TABLE integration_event_inbox NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE integration_event_inbox DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_integration_event_inbox_received_pending", table_name="integration_event_inbox")
    op.drop_index("ix_integration_event_inbox_tenant_received", table_name="integration_event_inbox")
    op.drop_table("integration_event_inbox")
