"""Link catalog entries to opportunities with immutable item snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_47"
down_revision = "20261025_46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_opportunity_catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_item_version", sa.Integer(), nullable=False),
        sa.Column("item_code_snapshot", sa.String(80), nullable=False),
        sa.Column("item_name_snapshot", sa.String(200), nullable=False),
        sa.Column("item_type_snapshot", sa.String(16), nullable=False),
        sa.Column("category_snapshot", sa.String(120), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_opportunity_catalog_items_tenant_id"),
        sa.UniqueConstraint("tenant_id", "opportunity_id", "catalog_item_id", name="uq_crm_opportunity_catalog_items_link"),
        sa.CheckConstraint("catalog_item_version >= 1", name="ck_crm_opportunity_catalog_items_version"),
        sa.CheckConstraint("item_type_snapshot IN ('product', 'service')", name="ck_crm_opportunity_catalog_items_type"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_opportunity_catalog_items_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "opportunity_id"], ["crm_opportunities.tenant_id", "crm_opportunities.id"], name="fk_crm_opportunity_catalog_items_opportunity", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "catalog_item_id"], ["crm_product_catalog_items.tenant_id", "crm_product_catalog_items.id"], name="fk_crm_opportunity_catalog_items_catalog", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_opportunity_catalog_items_creator", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_opportunity_catalog_items_tenant_opportunity", "crm_opportunity_catalog_items", ["tenant_id", "opportunity_id"])
    op.execute("ALTER TABLE crm_opportunity_catalog_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_opportunity_catalog_items FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON crm_opportunity_catalog_items USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_opportunity_catalog_items")
    op.execute("ALTER TABLE crm_opportunity_catalog_items NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_opportunity_catalog_items DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_opportunity_catalog_items_tenant_opportunity", table_name="crm_opportunity_catalog_items")
    op.drop_table("crm_opportunity_catalog_items")
