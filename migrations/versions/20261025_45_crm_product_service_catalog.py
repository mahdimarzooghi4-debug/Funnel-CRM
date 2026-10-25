"""Add tenant-scoped product/service catalog and immutable price versions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_45"
down_revision = "20261025_44"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "crm_product_catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("item_type", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_product_catalog_items_tenant_id"),
        sa.UniqueConstraint("tenant_id", "organization_unit_id", "code", name="uq_crm_product_catalog_items_code"),
        sa.CheckConstraint("item_type IN ('product', 'service')", name="ck_crm_product_catalog_items_type"),
        sa.CheckConstraint("length(trim(code)) BETWEEN 1 AND 80", name="ck_crm_product_catalog_items_code"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="ck_crm_product_catalog_items_name"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_product_catalog_items_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"], ["organization_units.tenant_id", "organization_units.id"], name="fk_crm_product_catalog_items_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_product_catalog_items_creator_same_tenant", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_product_catalog_items_tenant_org", "crm_product_catalog_items", ["tenant_id", "organization_unit_id", "is_active"])
    op.create_table(
        "crm_product_catalog_price_versions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_start", sa.Date(), nullable=True),
        sa.Column("effective_end", sa.Date(), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "item_id", "version"),
        sa.CheckConstraint("version >= 1", name="ck_crm_product_catalog_price_versions_version"),
        sa.CheckConstraint("amount >= 0", name="ck_crm_product_catalog_price_versions_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_product_catalog_price_versions_currency"),
        sa.CheckConstraint("effective_start IS NULL OR effective_end IS NULL OR effective_start <= effective_end", name="ck_crm_product_catalog_price_versions_window"),
        sa.ForeignKeyConstraint(["tenant_id", "item_id"], ["crm_product_catalog_items.tenant_id", "crm_product_catalog_items.id"], name="fk_crm_product_catalog_prices_item_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_product_catalog_prices_creator_same_tenant", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_product_catalog_prices_tenant_item", "crm_product_catalog_price_versions", ["tenant_id", "item_id", "version"])
    _rls("crm_product_catalog_items")
    _rls("crm_product_catalog_price_versions")
    op.execute("""
        CREATE FUNCTION reject_crm_catalog_price_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'product catalog price versions are append-only';
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER crm_product_catalog_prices_append_only
        BEFORE UPDATE OR DELETE ON crm_product_catalog_price_versions
        FOR EACH ROW EXECUTE FUNCTION reject_crm_catalog_price_mutation()
    """)
    permissions = sa.table("permission_definitions", sa.column("key", sa.String(160)), sa.column("description", sa.String(500)))
    op.bulk_insert(permissions, [
        {"key": "crm.catalog:view", "description": "View product and service catalog in authorized organization scopes"},
        {"key": "crm.catalog:manage", "description": "Manage product and service catalog in authorized organization scopes"},
    ])


def downgrade() -> None:
    op.execute("DROP TRIGGER crm_product_catalog_prices_append_only ON crm_product_catalog_price_versions")
    op.execute("DROP FUNCTION reject_crm_catalog_price_mutation()")
    for table in ("crm_product_catalog_price_versions", "crm_product_catalog_items"):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_product_catalog_prices_tenant_item", table_name="crm_product_catalog_price_versions")
    op.drop_table("crm_product_catalog_price_versions")
    op.drop_index("ix_crm_product_catalog_items_tenant_org", table_name="crm_product_catalog_items")
    op.drop_table("crm_product_catalog_items")
    op.execute("DELETE FROM role_permissions WHERE permission_key IN ('crm.catalog:view', 'crm.catalog:manage')")
    op.execute("DELETE FROM permission_definitions WHERE key IN ('crm.catalog:view', 'crm.catalog:manage')")
