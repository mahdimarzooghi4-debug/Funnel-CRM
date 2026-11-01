"""Persist immutable commission plan rule versions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_41"
down_revision = "20261025_40"
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
        "crm_commission_plan_versions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("seller_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("rate_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("changed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "plan_id", "version"),
        sa.CheckConstraint("version >= 1", name="ck_crm_commission_plan_versions_version_positive"),
        sa.CheckConstraint("rate_percent > 0 AND rate_percent <= 100", name="ck_crm_commission_plan_versions_rate"),
        sa.ForeignKeyConstraint(["tenant_id", "plan_id"], ["crm_commission_plans.tenant_id", "crm_commission_plans.id"], name="fk_crm_commission_plan_versions_plan_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "seller_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_commission_plan_versions_seller_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "changed_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], name="fk_crm_commission_plan_versions_actor_same_tenant", ondelete="CASCADE"),
    )
    op.create_index("ix_crm_commission_plan_versions_tenant_plan", "crm_commission_plan_versions", ["tenant_id", "plan_id", "version"])
    op.execute("""
        INSERT INTO crm_commission_plan_versions
            (tenant_id, plan_id, version, seller_membership_id, name, rate_percent, is_active, changed_by_membership_id)
        SELECT tenant_id, id, version, seller_membership_id, name, rate_percent, is_active, created_by_membership_id
        FROM crm_commission_plans
    """)
    op.create_foreign_key(
        "fk_crm_commission_calculations_plan_version_same_tenant",
        "crm_commission_calculations", "crm_commission_plan_versions",
        ["tenant_id", "plan_id", "plan_version"], ["tenant_id", "plan_id", "version"],
        ondelete="RESTRICT",
    )
    _rls("crm_commission_plan_versions")
    op.execute("""
        CREATE TRIGGER crm_commission_plan_versions_append_only
        BEFORE UPDATE OR DELETE ON crm_commission_plan_versions
        FOR EACH ROW EXECUTE FUNCTION reject_commission_snapshot_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER crm_commission_plan_versions_append_only ON crm_commission_plan_versions")
    op.drop_constraint(
        "fk_crm_commission_calculations_plan_version_same_tenant",
        "crm_commission_calculations", type_="foreignkey",
    )
    op.execute("DROP POLICY tenant_isolation ON crm_commission_plan_versions")
    op.execute("ALTER TABLE crm_commission_plan_versions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_commission_plan_versions DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_commission_plan_versions_tenant_plan", table_name="crm_commission_plan_versions")
    op.drop_table("crm_commission_plan_versions")
