"""Add seller commission plans and immutable calculation snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_39"
down_revision = "20261025_38"
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
        "crm_commission_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("rate_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_commission_plans_tenant_id"),
        sa.CheckConstraint("rate_percent > 0 AND rate_percent <= 100", name="ck_crm_commission_plans_rate"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_commission_plans_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"], ["organization_units.tenant_id", "organization_units.id"], name="fk_crm_commission_plans_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "seller_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_commission_plans_seller_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_commission_plans_creator_same_tenant", ondelete="RESTRICT"),
    )
    op.create_index("ix_crm_commission_plans_tenant_org", "crm_commission_plans", ["tenant_id", "organization_unit_id"])
    op.create_table(
        "crm_commission_calculations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("rate_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_commission_calculations_tenant_id"),
        sa.CheckConstraint("period_start <= period_end", name="ck_crm_commission_calculations_period"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], name="fk_crm_commission_calculations_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "plan_id"], ["crm_commission_plans.tenant_id", "crm_commission_plans.id"], name="fk_crm_commission_calculations_plan_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_commission_calculations_creator_same_tenant", ondelete="RESTRICT"),
    )
    op.create_index("ix_crm_commission_calculations_tenant_plan", "crm_commission_calculations", ["tenant_id", "plan_id", "created_at"])
    op.create_table(
        "crm_commission_calculation_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("paid_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("refunded_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("net_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("commission_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("source_event_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_commission_rows_currency"),
        sa.UniqueConstraint("tenant_id", "calculation_id", "seller_membership_id", "currency", name="uq_crm_commission_rows_seller_currency"),
        sa.ForeignKeyConstraint(["tenant_id", "calculation_id"], ["crm_commission_calculations.tenant_id", "crm_commission_calculations.id"], name="fk_crm_commission_rows_calculation_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "seller_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_commission_rows_seller_same_tenant", ondelete="RESTRICT"),
    )
    for table in ("crm_commission_plans", "crm_commission_calculations", "crm_commission_calculation_rows"):
        _rls(table)
    op.execute("""
        CREATE FUNCTION reject_commission_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'commission calculation snapshots are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER crm_commission_calculations_append_only
        BEFORE UPDATE OR DELETE ON crm_commission_calculations
        FOR EACH ROW EXECUTE FUNCTION reject_commission_snapshot_mutation()
    """)
    op.execute("""
        CREATE TRIGGER crm_commission_rows_append_only
        BEFORE UPDATE OR DELETE ON crm_commission_calculation_rows
        FOR EACH ROW EXECUTE FUNCTION reject_commission_snapshot_mutation()
    """)
    permissions = sa.table("permission_definitions", sa.column("key", sa.String(160)), sa.column("description", sa.String(500)))
    op.bulk_insert(permissions, [
        {"key": "crm.commission:view", "description": "View commission plans and calculation snapshots in authorized organization scopes"},
        {"key": "crm.commission:manage", "description": "Manage commission plans and create calculation snapshots"},
    ])


def downgrade() -> None:
    op.execute("DROP TRIGGER crm_commission_rows_append_only ON crm_commission_calculation_rows")
    op.execute("DROP TRIGGER crm_commission_calculations_append_only ON crm_commission_calculations")
    op.execute("DROP FUNCTION reject_commission_snapshot_mutation()")
    for table in ("crm_commission_calculation_rows", "crm_commission_calculations", "crm_commission_plans"):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_commission_calculation_rows")
    op.drop_index("ix_crm_commission_calculations_tenant_plan", table_name="crm_commission_calculations")
    op.drop_table("crm_commission_calculations")
    op.drop_index("ix_crm_commission_plans_tenant_org", table_name="crm_commission_plans")
    op.drop_table("crm_commission_plans")
    op.execute("DELETE FROM role_permissions WHERE permission_key IN ('crm.commission:view', 'crm.commission:manage')")
    op.execute("DELETE FROM permission_definitions WHERE key IN ('crm.commission:view', 'crm.commission:manage')")
