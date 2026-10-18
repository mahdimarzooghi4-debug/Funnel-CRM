"""Create tenant-scoped product connections and hashed bearer credentials.

Revision ID: 20261018_12
Revises: 20261018_11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_12"
down_revision = "20261018_11"
branch_labels = None
depends_on = None

PERMISSION = ("crm.integration:manage", "Manage connected product credentials")


def upgrade() -> None:
    op.execute(
        "INSERT INTO permission_definitions (key, description) "
        f"VALUES ('{PERMISSION[0]}', '{PERMISSION[1]}') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.create_table(
        "product_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_digest", sa.LargeBinary(), nullable=False),
        sa.Column("source_product", sa.String(length=80), nullable=False),
        sa.Column("allowed_event_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contract_grants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source_product ~ '^[a-z0-9][a-z0-9._-]{1,79}$'", name="ck_product_connections_source"),
        sa.CheckConstraint("octet_length(credential_digest) = 32", name="ck_product_connections_credential_digest"),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_event_types) = 'array' AND jsonb_array_length(allowed_event_types) BETWEEN 1 AND 50 AND octet_length(allowed_event_types::text) <= 8192",
            name="ck_product_connections_event_grants",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(contract_grants) = 'array' AND jsonb_array_length(contract_grants) BETWEEN 1 AND 50 AND octet_length(contract_grants::text) <= 8192",
            name="ck_product_connections_contract_grants",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_product_connections_workspace", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_connections_tenant_id"),
        sa.UniqueConstraint("tenant_id", "credential_id", name="uq_product_connections_tenant_credential"),
    )
    op.create_index("ix_product_connections_tenant_created", "product_connections", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE product_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_connections FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON product_connections
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON product_connections")
    op.execute("ALTER TABLE product_connections NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_connections DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_product_connections_tenant_created", table_name="product_connections")
    op.drop_table("product_connections")
    op.execute("DELETE FROM role_permissions WHERE permission_key = 'crm.integration:manage'")
    op.execute("DELETE FROM permission_definitions WHERE key = 'crm.integration:manage'")
