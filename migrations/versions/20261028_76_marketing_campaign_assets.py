"""Add scoped marketing campaign assets and review states."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261028_76"
down_revision = "20261028_75"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_campaign_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("asset_kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.String(length=12000), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("locale", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_note", sa.String(length=2000), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 160", name="ck_crm_marketing_campaign_assets_title"),
        sa.CheckConstraint(
            "channel IN ('email', 'phone', 'messaging', 'social', 'web', 'store', 'field', 'other')",
            name="ck_crm_marketing_campaign_assets_channel",
        ),
        sa.CheckConstraint(
            "asset_kind IN ('copy', 'image', 'video', 'landing_page', 'document', 'other')",
            name="ck_crm_marketing_campaign_assets_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'retired')",
            name="ck_crm_marketing_campaign_assets_status",
        ),
        sa.CheckConstraint("body IS NOT NULL OR external_url IS NOT NULL", name="ck_crm_marketing_campaign_assets_content"),
        sa.CheckConstraint(
            "locale IS NULL OR locale ~ '^[a-z]{2}(-[A-Z]{2})?$'",
            name="ck_crm_marketing_campaign_assets_locale",
        ),
        sa.CheckConstraint(
            "(status IN ('approved', 'rejected') AND reviewed_by_membership_id IS NOT NULL AND reviewed_at IS NOT NULL) OR "
            "(status NOT IN ('approved', 'rejected') AND reviewed_by_membership_id IS NULL AND reviewed_at IS NULL)",
            name="ck_crm_marketing_campaign_assets_review_state",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR review_note IS NOT NULL",
            name="ck_crm_marketing_campaign_assets_rejection_note",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_assets_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_assets_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_assets_campaign_same_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_marketing_campaign_assets_creator_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "reviewed_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_marketing_campaign_assets_reviewer_same_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_assets_tenant_id"),
    )
    op.create_index(
        "ix_crm_marketing_campaign_assets_tenant_org_status",
        "crm_marketing_campaign_assets",
        ["tenant_id", "organization_unit_id", "status"],
    )
    op.create_index(
        "ix_crm_marketing_campaign_assets_tenant_campaign",
        "crm_marketing_campaign_assets",
        ["tenant_id", "campaign_id"],
    )
    op.execute("ALTER TABLE crm_marketing_campaign_assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaign_assets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_marketing_campaign_assets
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_campaign_assets")
    op.execute("ALTER TABLE crm_marketing_campaign_assets NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaign_assets DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_marketing_campaign_assets_tenant_campaign", table_name="crm_marketing_campaign_assets")
    op.drop_index("ix_crm_marketing_campaign_assets_tenant_org_status", table_name="crm_marketing_campaign_assets")
    op.drop_table("crm_marketing_campaign_assets")
