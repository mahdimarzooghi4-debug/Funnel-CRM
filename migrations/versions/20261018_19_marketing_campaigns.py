"""Add draft marketing campaigns and campaign permissions.

Revision ID: 20261018_19
Revises: 20261018_18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_19"
down_revision = "20261018_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("objective_key", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaigns_tenant_id"),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_crm_marketing_campaigns_name",
        ),
        sa.CheckConstraint(
            "objective_key ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_marketing_campaigns_objective",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'phone', 'messaging', 'social', 'web', 'store', 'field', 'other')",
            name="ck_crm_marketing_campaigns_channel",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'archived')",
            name="ck_crm_marketing_campaigns_status",
        ),
        sa.CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR starts_at < ends_at",
            name="ck_crm_marketing_campaigns_schedule_order",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_marketing_campaigns_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaigns_org_same_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "segment_id"],
            ["crm_profile_segments.tenant_id", "crm_profile_segments.id"],
            name="fk_crm_marketing_campaigns_segment_same_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_marketing_campaigns_tenant_org_status",
        "crm_marketing_campaigns",
        ["tenant_id", "organization_unit_id", "status"],
    )
    op.execute("ALTER TABLE crm_marketing_campaigns ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaigns FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_marketing_campaigns
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        INSERT INTO permission_definitions (key, description)
        VALUES
            ('crm.campaign:view', 'View marketing campaign plans in an authorized organization scope'),
            ('crm.campaign:manage', 'Create, update, and archive marketing campaign plans in an authorized organization scope')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key IN ('crm.campaign:view', 'crm.campaign:manage')"
    )
    op.execute(
        "DELETE FROM permission_definitions WHERE key IN ('crm.campaign:view', 'crm.campaign:manage')"
    )
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_campaigns")
    op.execute(
        "ALTER TABLE crm_marketing_campaigns NO FORCE ROW LEVEL SECURITY"
    )
    op.execute("ALTER TABLE crm_marketing_campaigns DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_crm_marketing_campaigns_tenant_org_status",
        table_name="crm_marketing_campaigns",
    )
    op.drop_table("crm_marketing_campaigns")
