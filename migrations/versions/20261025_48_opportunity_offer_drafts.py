"""Add non-binding opportunity offer draft snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_48"
down_revision = "20261025_47"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def upgrade() -> None:
    op.create_table(
        "crm_opportunity_offer_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_opportunity_offer_drafts_tenant_id"),
        sa.CheckConstraint("status = 'draft'", name="ck_crm_opportunity_offer_drafts_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_opportunity_offer_drafts_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "opportunity_id"], ["crm_opportunities.tenant_id", "crm_opportunities.id"], name="fk_crm_opportunity_offer_drafts_opportunity", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_opportunity_offer_drafts_creator", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_opportunity_offer_drafts_tenant_opportunity", "crm_opportunity_offer_drafts", ["tenant_id", "opportunity_id", "created_at"])
    op.create_table(
        "crm_opportunity_offer_draft_lines",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("catalog_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_item_version", sa.Integer(), nullable=False),
        sa.Column("catalog_price_version", sa.Integer(), nullable=False),
        sa.Column("item_code_snapshot", sa.String(80), nullable=False),
        sa.Column("item_name_snapshot", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "offer_id", "line_number"),
        sa.CheckConstraint("line_number >= 1", name="ck_crm_opportunity_offer_draft_lines_number"),
        sa.CheckConstraint("quantity > 0", name="ck_crm_opportunity_offer_draft_lines_quantity"),
        sa.CheckConstraint("unit_amount >= 0", name="ck_crm_opportunity_offer_draft_lines_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_opportunity_offer_draft_lines_currency"),
        sa.ForeignKeyConstraint(["tenant_id", "offer_id"], ["crm_opportunity_offer_drafts.tenant_id", "crm_opportunity_offer_drafts.id"], name="fk_crm_opportunity_offer_draft_lines_offer", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "catalog_item_id"], ["crm_product_catalog_items.tenant_id", "crm_product_catalog_items.id"], name="fk_crm_opportunity_offer_draft_lines_catalog", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "catalog_item_id", "catalog_price_version"], ["crm_product_catalog_price_versions.tenant_id", "crm_product_catalog_price_versions.item_id", "crm_product_catalog_price_versions.version"], name="fk_crm_opportunity_offer_draft_lines_price", ondelete="RESTRICT"),
    )
    op.create_index("ix_crm_opportunity_offer_draft_lines_tenant_offer", "crm_opportunity_offer_draft_lines", ["tenant_id", "offer_id", "line_number"])
    _rls("crm_opportunity_offer_drafts")
    _rls("crm_opportunity_offer_draft_lines")
    permissions = sa.table("permission_definitions", sa.column("key", sa.String(160)), sa.column("description", sa.String(500)))
    op.bulk_insert(permissions, [
        {"key": "crm.offer:view", "description": "View offer drafts in authorized opportunity scopes"},
        {"key": "crm.offer:create", "description": "Create offer drafts in authorized opportunity scopes"},
    ])


def downgrade() -> None:
    for table in ("crm_opportunity_offer_draft_lines", "crm_opportunity_offer_drafts"):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_opportunity_offer_draft_lines_tenant_offer", table_name="crm_opportunity_offer_draft_lines")
    op.drop_table("crm_opportunity_offer_draft_lines")
    op.drop_index("ix_crm_opportunity_offer_drafts_tenant_opportunity", table_name="crm_opportunity_offer_drafts")
    op.drop_table("crm_opportunity_offer_drafts")
    op.execute("DELETE FROM role_permissions WHERE permission_key IN ('crm.offer:view', 'crm.offer:create')")
    op.execute("DELETE FROM permission_definitions WHERE key IN ('crm.offer:view', 'crm.offer:create')")
