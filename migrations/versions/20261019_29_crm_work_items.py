"""Add organization-scoped CRM work items and permissions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_29"
down_revision = "20261018_28"
branch_labels = None
depends_on = None

PERMISSIONS = (
    "crm.work_item:view",
    "crm.work_item:create",
    "crm.work_item:update",
)


def upgrade() -> None:
    op.create_table(
        "crm_work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_work_items_tenant_id"),
        sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 200",
                           name="ck_crm_work_items_title"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')",
                           name="ck_crm_work_items_priority"),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'completed', 'cancelled')",
            name="ck_crm_work_items_status"),
        sa.CheckConstraint(
            "profile_id IS NOT NULL OR opportunity_id IS NOT NULL OR campaign_id IS NOT NULL",
            name="ck_crm_work_items_has_context"),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name="ck_crm_work_items_completion_timestamp"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_work_items_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_work_items_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_work_items_profile_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "opportunity_id"],
            ["crm_opportunities.tenant_id", "crm_opportunities.id"],
            name="fk_crm_work_items_opportunity_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_work_items_campaign_same_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "assigned_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_items_assignee_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_items_creator_same_tenant", ondelete="RESTRICT"),
        sa.Index("ix_crm_work_items_tenant_org_status_due",
                 "tenant_id", "organization_unit_id", "status", "due_at"),
        sa.Index("ix_crm_work_items_tenant_assignee_status_due",
                 "tenant_id", "assigned_membership_id", "status", "due_at"),
    )
    permission_table = sa.table(
        "permission_definitions",
        sa.column("key", sa.String(160)),
        sa.column("description", sa.String(500)),
    )
    op.bulk_insert(permission_table, [
        {"key": "crm.work_item:view", "description": "View CRM work items in authorized organization scopes"},
        {"key": "crm.work_item:create", "description": "Create CRM work items in authorized organization scopes"},
        {"key": "crm.work_item:update", "description": "Update CRM work items in authorized organization scopes"},
    ])
    op.execute("ALTER TABLE crm_work_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_work_items FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_work_items "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_work_items")
    op.execute("ALTER TABLE crm_work_items NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_work_items DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_work_items")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key IN "
        "('crm.work_item:view', 'crm.work_item:create', 'crm.work_item:update')"
    )
    op.execute(
        "DELETE FROM permission_definitions WHERE key IN "
        "('crm.work_item:view', 'crm.work_item:create', 'crm.work_item:update')"
    )
