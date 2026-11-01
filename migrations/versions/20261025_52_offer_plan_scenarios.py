"""Add immutable assumption-based marketing offer scenarios."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_52"
down_revision = "20261025_51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_offer_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("audience_size", sa.Integer(), nullable=False),
        sa.Column("expected_use_rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("catalog_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("catalog_item_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("price_version", sa.Integer(), nullable=True),
        sa.Column("unit_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("offer_value_per_use", sa.Numeric(20, 6), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("campaign_budget_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("campaign_budget_currency", sa.String(3), nullable=True),
        sa.Column("assumptions", sa.String(4000), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_offer_scenarios_tenant_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 160", name="ck_crm_marketing_offer_scenarios_name"),
        sa.CheckConstraint("audience_size >= 0", name="ck_crm_marketing_offer_scenarios_audience"),
        sa.CheckConstraint("expected_use_rate >= 0 AND expected_use_rate <= 100", name="ck_crm_marketing_offer_scenarios_use_rate"),
        sa.CheckConstraint("plan_version >= 1 AND catalog_item_version >= 1", name="ck_crm_marketing_offer_scenarios_versions"),
        sa.CheckConstraint("(price_version IS NULL AND unit_amount IS NULL AND offer_value_per_use IS NULL AND currency IS NULL) OR (price_version IS NOT NULL AND unit_amount IS NOT NULL AND offer_value_per_use IS NOT NULL AND currency IS NOT NULL)", name="ck_crm_marketing_offer_scenarios_price_snapshot"),
        sa.CheckConstraint("unit_amount IS NULL OR (offer_value_per_use >= 0 AND offer_value_per_use <= unit_amount)", name="ck_crm_marketing_offer_scenarios_offer_value"),
        sa.CheckConstraint("(campaign_budget_amount IS NULL AND campaign_budget_currency IS NULL) OR (campaign_budget_amount IS NOT NULL AND campaign_budget_amount >= 0 AND campaign_budget_currency ~ '^[A-Z]{3}$')", name="ck_crm_marketing_offer_scenarios_budget_pair"),
        sa.CheckConstraint("length(trim(assumptions)) BETWEEN 1 AND 4000", name="ck_crm_marketing_offer_scenarios_assumptions"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_marketing_offer_scenarios_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "offer_plan_id"], ["crm_marketing_offer_plans.tenant_id", "crm_marketing_offer_plans.id"], name="fk_crm_marketing_offer_scenarios_plan", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_marketing_offer_scenarios_creator", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_marketing_offer_scenarios_tenant_plan", "crm_marketing_offer_scenarios", ["tenant_id", "offer_plan_id", "created_at"])
    op.execute("ALTER TABLE crm_marketing_offer_scenarios ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_offer_scenarios FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON crm_marketing_offer_scenarios USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    permissions = sa.table("permission_definitions", sa.column("key", sa.String(160)), sa.column("description", sa.String(500)))
    op.bulk_insert(permissions, [{"key": "crm.offer_plan:scenario", "description": "Create and compare offer plan economic scenarios in authorized scopes"}])


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_key = 'crm.offer_plan:scenario'")
    op.execute("DELETE FROM permission_definitions WHERE key = 'crm.offer_plan:scenario'")
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_offer_scenarios")
    op.execute("ALTER TABLE crm_marketing_offer_scenarios NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_offer_scenarios DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_marketing_offer_scenarios_tenant_plan", table_name="crm_marketing_offer_scenarios")
    op.drop_table("crm_marketing_offer_scenarios")
