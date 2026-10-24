"""Add organization-scoped CRM customer support cases."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261024_32"
down_revision = "20261019_31"
branch_labels = None
depends_on = None

PERMISSIONS = (
    "crm.support_case:view",
    "crm.support_case:create",
    "crm.support_case:update",
)


def upgrade() -> None:
    op.create_table(
        "crm_support_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("description", sa.String(4000), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_support_cases_tenant_id"),
        sa.CheckConstraint("length(trim(subject)) BETWEEN 1 AND 200",
                           name="ck_crm_support_cases_subject"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')",
                           name="ck_crm_support_cases_priority"),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_customer', 'resolved', 'closed')",
            name="ck_crm_support_cases_status"),
        sa.CheckConstraint(
            "(status IN ('resolved', 'closed') AND resolved_at IS NOT NULL) OR "
            "(status NOT IN ('resolved', 'closed') AND resolved_at IS NULL)",
            name="ck_crm_support_cases_resolution_timestamp"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_support_cases_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_support_cases_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_support_cases_profile_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "assigned_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_support_cases_assignee_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_support_cases_creator_same_tenant", ondelete="RESTRICT"),
        sa.Index("ix_crm_support_cases_tenant_org_status_due",
                 "tenant_id", "organization_unit_id", "status", "response_due_at"),
        sa.Index("ix_crm_support_cases_tenant_assignee_status_due",
                 "tenant_id", "assigned_membership_id", "status", "response_due_at"),
    )
    permission_table = sa.table(
        "permission_definitions",
        sa.column("key", sa.String(160)),
        sa.column("description", sa.String(500)),
    )
    op.bulk_insert(permission_table, [
        {"key": "crm.support_case:view", "description": "View customer support cases in authorized organization scopes"},
        {"key": "crm.support_case:create", "description": "Create customer support cases in authorized organization scopes"},
        {"key": "crm.support_case:update", "description": "Update customer support cases in authorized organization scopes"},
    ])
    op.execute("ALTER TABLE crm_support_cases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_support_cases FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_support_cases "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_support_cases")
    op.execute("ALTER TABLE crm_support_cases NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_support_cases DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_support_cases")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key IN "
        "('crm.support_case:view', 'crm.support_case:create', 'crm.support_case:update')"
    )
    op.execute(
        "DELETE FROM permission_definitions WHERE key IN "
        "('crm.support_case:view', 'crm.support_case:create', 'crm.support_case:update')"
    )
