"""Add tenant-scoped marketing budget scenarios and allocations.

Revision ID: 20261018_21
Revises: 20261018_20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_21"
down_revision = "20261018_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_crm_marketing_campaigns_tenant_org_id",
        "crm_marketing_campaigns",
        ["tenant_id", "organization_unit_id", "id"],
    )
    op.create_table(
        "crm_marketing_budget_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_budget_scenarios_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "id", "organization_unit_id",
            name="uq_crm_marketing_budget_scenarios_tenant_id_org",
        ),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 160", name="ck_crm_marketing_budget_scenarios_name"),
        sa.CheckConstraint("status IN ('draft', 'archived')", name="ck_crm_marketing_budget_scenarios_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_budget_scenarios_workspace", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_budget_scenarios_org_same_tenant", ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "crm_marketing_budget_scenario_lines",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planned_budget_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("planned_budget_currency", sa.String(3), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "scenario_id", "campaign_id",
            name="pk_crm_marketing_budget_scenario_lines",
        ),
        sa.CheckConstraint(
            "planned_budget_amount >= 0 AND length(planned_budget_currency) = 3 "
            "AND planned_budget_currency = upper(planned_budget_currency) "
            "AND planned_budget_currency ~ '^[A-Z][A-Z][A-Z]'",
            name="ck_crm_marketing_budget_scenario_lines_budget",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "scenario_id", "organization_unit_id"],
            ["crm_marketing_budget_scenarios.tenant_id", "crm_marketing_budget_scenarios.id",
             "crm_marketing_budget_scenarios.organization_unit_id"],
            name="fk_crm_marketing_budget_scenario_lines_scenario_same_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_budget_scenario_lines_campaign_same_org",
            ondelete="CASCADE",
        ),
        sa.Index(
            "ix_crm_marketing_budget_scenario_lines_scenario",
            "tenant_id", "scenario_id",
        ),
    )
    for table in ("crm_marketing_budget_scenarios", "crm_marketing_budget_scenario_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute(
        """
        INSERT INTO permission_definitions (key, description)
        VALUES
            ('crm.budget_scenario:view', 'View marketing budget scenarios in an authorized organization scope'),
            ('crm.budget_scenario:manage', 'Create, update, and archive marketing budget scenarios in an authorized organization scope')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key IN "
        "('crm.budget_scenario:view', 'crm.budget_scenario:manage')"
    )
    op.execute(
        "DELETE FROM permission_definitions WHERE key IN "
        "('crm.budget_scenario:view', 'crm.budget_scenario:manage')"
    )
    for table in ("crm_marketing_budget_scenario_lines", "crm_marketing_budget_scenarios"):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_marketing_budget_scenario_lines")
    op.drop_table("crm_marketing_budget_scenarios")
    op.drop_constraint(
        "uq_crm_marketing_campaigns_tenant_org_id",
        "crm_marketing_campaigns",
        type_="unique",
    )
