"""Add idempotent campaign measurement import batches.

Revision ID: 20261018_23
Revises: 20261018_22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_23"
down_revision = "20261018_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_measurement_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_measurement_import_batches_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "campaign_id", "idempotency_key",
            name="uq_crm_marketing_measurement_import_batches_campaign_key",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) BETWEEN 1 AND 80",
            name="ck_crm_marketing_measurement_import_batches_key",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}'",
            name="ck_crm_marketing_measurement_import_batches_hash",
        ),
        sa.CheckConstraint(
            "row_count BETWEEN 1 AND 366 AND created_count >= 0 AND updated_count >= 0 "
            "AND created_count + updated_count = row_count",
            name="ck_crm_marketing_measurement_import_batches_counts",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_measurement_import_batches_workspace", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_measurement_import_batches_org_same_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_measurement_import_batches_campaign_same_org", ondelete="CASCADE",
        ),
        sa.Index(
            "ix_crm_marketing_measurement_import_batches_tenant_campaign",
            "tenant_id", "campaign_id",
        ),
    )
    op.execute("ALTER TABLE crm_marketing_measurement_import_batches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_measurement_import_batches FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_marketing_measurement_import_batches "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_measurement_import_batches")
    op.execute("ALTER TABLE crm_marketing_measurement_import_batches NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_measurement_import_batches DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_marketing_measurement_import_batches")
