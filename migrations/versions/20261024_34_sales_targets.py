"""Add organization and pipeline sales targets."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261024_34"
down_revision = "20261024_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_sales_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("target_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_sales_targets_tenant_id"),
        sa.UniqueConstraint("tenant_id", "organization_unit_id", "pipeline_id", "period_start", "period_end", "currency",
                            name="uq_crm_sales_targets_period_currency"),
        sa.CheckConstraint("target_amount > 0", name="ck_crm_sales_targets_positive_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_sales_targets_currency"),
        sa.CheckConstraint("period_start <= period_end", name="ck_crm_sales_targets_period"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_sales_targets_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"], ["organization_units.tenant_id", "organization_units.id"],
                                name="fk_crm_sales_targets_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "pipeline_id"], ["crm_pipelines.tenant_id", "crm_pipelines.id"],
                                name="fk_crm_sales_targets_pipeline_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"],
                                name="fk_crm_sales_targets_creator_same_tenant", ondelete="RESTRICT"),
    )
    op.create_index("ix_crm_sales_targets_tenant_org_period", "crm_sales_targets",
                    ["tenant_id", "organization_unit_id", "period_start", "period_end"])
    op.execute("ALTER TABLE crm_sales_targets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_sales_targets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_sales_targets "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_sales_targets")
    op.execute("ALTER TABLE crm_sales_targets NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_sales_targets DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_sales_targets_tenant_org_period", table_name="crm_sales_targets")
    op.drop_table("crm_sales_targets")
