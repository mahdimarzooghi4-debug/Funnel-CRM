"""Create sales opportunity pipeline records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_27"
down_revision = "20261018_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("stage_key", sa.String(80), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_opportunities_tenant_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="ck_crm_opportunities_name"),
        sa.CheckConstraint(
            "stage_key ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_opportunities_stage_key",
        ),
        sa.CheckConstraint(
            "(amount IS NULL AND currency IS NULL) OR "
            "(amount IS NOT NULL AND amount >= 0 AND currency IS NOT NULL "
            "AND currency ~ '^[A-Z]{3}$')",
            name="ck_crm_opportunities_amount_currency",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
                                name="fk_crm_opportunities_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
                                ["organization_units.tenant_id", "organization_units.id"],
                                name="fk_crm_opportunities_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "profile_id"],
                                ["crm_profiles.tenant_id", "crm_profiles.id"],
                                name="fk_crm_opportunities_profile_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "pipeline_id"],
                                ["crm_pipelines.tenant_id", "crm_pipelines.id"],
                                name="fk_crm_opportunities_pipeline_same_tenant", ondelete="RESTRICT"),
        sa.Index("ix_crm_opportunities_tenant_org_stage",
                 "tenant_id", "organization_unit_id", "pipeline_id", "stage_key"),
        sa.Index("ix_crm_opportunities_tenant_profile", "tenant_id", "profile_id"),
    )
    permission_table = sa.table(
        "permission_definitions",
        sa.column("key", sa.String(160)),
        sa.column("description", sa.String(500)),
    )
    op.bulk_insert(permission_table, [
        {"key": "crm.opportunity:view", "description": "View opportunities in authorized CRM organization scopes"},
        {"key": "crm.opportunity:create", "description": "Create opportunities in authorized CRM organization scopes"},
        {"key": "crm.opportunity:update", "description": "Update opportunities in authorized CRM organization scopes"},
    ])
    op.execute("ALTER TABLE crm_opportunities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_opportunities FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_opportunities "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_opportunities")
    op.execute("ALTER TABLE crm_opportunities NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_opportunities DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_opportunities")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key IN "
        "('crm.opportunity:view', 'crm.opportunity:create', 'crm.opportunity:update')"
    )
    op.execute(
        "DELETE FROM permission_definitions WHERE key IN "
        "('crm.opportunity:view', 'crm.opportunity:create', 'crm.opportunity:update')"
    )
