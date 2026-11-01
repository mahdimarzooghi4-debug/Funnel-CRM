"""Add configurable marketing offer planning drafts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_50"
down_revision = "20261025_49"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_offer_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("objective", sa.String(2000), nullable=False),
        sa.Column("offer_type", sa.String(80), nullable=False),
        sa.Column("catalog_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audience_description", sa.String(1000), nullable=False),
        sa.Column("channel", sa.String(80), nullable=False),
        sa.Column("location_scope", sa.String(250), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eligibility_conditions", sa.String(4000), nullable=True),
        sa.Column("success_metric", sa.String(500), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_offer_plans_tenant_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 160", name="ck_crm_marketing_offer_plans_name"),
        sa.CheckConstraint("length(trim(objective)) BETWEEN 1 AND 2000", name="ck_crm_marketing_offer_plans_objective"),
        sa.CheckConstraint("status = 'draft'", name="ck_crm_marketing_offer_plans_status"),
        sa.CheckConstraint("version >= 1", name="ck_crm_marketing_offer_plans_version"),
        sa.CheckConstraint("starts_at IS NULL OR ends_at IS NULL OR starts_at < ends_at", name="ck_crm_marketing_offer_plans_schedule"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_marketing_offer_plans_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"], ["organization_units.tenant_id", "organization_units.id"], name="fk_crm_marketing_offer_plans_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "campaign_id"], ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.id"], name="fk_crm_marketing_offer_plans_campaign", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "catalog_item_id"], ["crm_product_catalog_items.tenant_id", "crm_product_catalog_items.id"], name="fk_crm_marketing_offer_plans_catalog_item", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "owner_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_marketing_offer_plans_owner", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_marketing_offer_plans_tenant_org_status", "crm_marketing_offer_plans", ["tenant_id", "organization_unit_id", "status"])
    op.execute("ALTER TABLE crm_marketing_offer_plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_offer_plans FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON crm_marketing_offer_plans USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    permissions = sa.table("permission_definitions", sa.column("key", sa.String(160)), sa.column("description", sa.String(500)))
    op.bulk_insert(permissions, [
        {"key": "crm.offer_plan:view", "description": "View marketing offer planning drafts in authorized scopes"},
        {"key": "crm.offer_plan:create", "description": "Create marketing offer planning drafts in authorized scopes"},
        {"key": "crm.offer_plan:update", "description": "Update marketing offer planning drafts in authorized scopes"},
    ])


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_offer_plans")
    op.execute("ALTER TABLE crm_marketing_offer_plans NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_offer_plans DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_marketing_offer_plans_tenant_org_status", table_name="crm_marketing_offer_plans")
    op.drop_table("crm_marketing_offer_plans")
    op.execute("DELETE FROM role_permissions WHERE permission_key IN ('crm.offer_plan:view', 'crm.offer_plan:create', 'crm.offer_plan:update')")
    op.execute("DELETE FROM permission_definitions WHERE key IN ('crm.offer_plan:view', 'crm.offer_plan:create', 'crm.offer_plan:update')")
