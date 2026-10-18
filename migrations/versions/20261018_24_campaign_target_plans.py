"""Add manager-entered targets for campaign periods.

Revision ID: 20261018_24
Revises: 20261018_23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_24"
down_revision = "20261018_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_campaign_target_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("impressions_target", sa.BigInteger(), nullable=True),
        sa.Column("clicks_target", sa.BigInteger(), nullable=True),
        sa.Column("leads_target", sa.BigInteger(), nullable=True),
        sa.Column("conversions_target", sa.BigInteger(), nullable=True),
        sa.Column("max_spend_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("max_spend_currency", sa.String(3), nullable=True),
        sa.Column("max_cpl_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("cpl_currency", sa.String(3), nullable=True),
        sa.Column("max_cost_per_conversion_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("conversion_cost_currency", sa.String(3), nullable=True),
        sa.Column("min_roas", sa.Numeric(20, 6), nullable=True),
        sa.Column("roas_currency", sa.String(3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_target_plans_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "campaign_id", "period_start", "period_end",
            name="uq_crm_marketing_campaign_target_plans_campaign_period",
        ),
        sa.CheckConstraint("period_start <= period_end AND period_end - period_start < 366",
                           name="ck_crm_marketing_campaign_target_plans_period"),
        sa.CheckConstraint(
            "(impressions_target IS NULL OR impressions_target >= 0) AND "
            "(clicks_target IS NULL OR clicks_target >= 0) AND "
            "(leads_target IS NULL OR leads_target >= 0) AND "
            "(conversions_target IS NULL OR conversions_target >= 0)",
            name="ck_crm_marketing_campaign_target_plans_counts",
        ),
        sa.CheckConstraint(
            "(max_spend_amount IS NULL AND max_spend_currency IS NULL) OR "
            "(max_spend_amount IS NOT NULL AND max_spend_amount >= 0 AND "
            "length(max_spend_currency) = 3 AND max_spend_currency = upper(max_spend_currency) "
            "AND max_spend_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_spend_pair",
        ),
        sa.CheckConstraint(
            "(max_cpl_amount IS NULL AND cpl_currency IS NULL) OR "
            "(max_cpl_amount IS NOT NULL AND max_cpl_amount >= 0 AND "
            "length(cpl_currency) = 3 AND cpl_currency = upper(cpl_currency) "
            "AND cpl_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_cpl_pair",
        ),
        sa.CheckConstraint(
            "(max_cost_per_conversion_amount IS NULL AND conversion_cost_currency IS NULL) OR "
            "(max_cost_per_conversion_amount IS NOT NULL AND max_cost_per_conversion_amount >= 0 AND "
            "length(conversion_cost_currency) = 3 AND conversion_cost_currency = upper(conversion_cost_currency) "
            "AND conversion_cost_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_conversion_cost_pair",
        ),
        sa.CheckConstraint(
            "(min_roas IS NULL AND roas_currency IS NULL) OR "
            "(min_roas IS NOT NULL AND min_roas >= 0 AND length(roas_currency) = 3 "
            "AND roas_currency = upper(roas_currency) AND roas_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_roas_pair",
        ),
        sa.CheckConstraint(
            "impressions_target IS NOT NULL OR clicks_target IS NOT NULL OR leads_target IS NOT NULL OR "
            "conversions_target IS NOT NULL OR max_spend_amount IS NOT NULL OR max_cpl_amount IS NOT NULL OR "
            "max_cost_per_conversion_amount IS NOT NULL OR min_roas IS NOT NULL",
            name="ck_crm_marketing_campaign_target_plans_has_goal",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_target_plans_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_target_plans_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_target_plans_campaign_same_org", ondelete="CASCADE"),
        sa.Index("ix_crm_marketing_campaign_target_plans_tenant_campaign",
                 "tenant_id", "campaign_id"),
    )
    op.execute("ALTER TABLE crm_marketing_campaign_target_plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaign_target_plans FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_marketing_campaign_target_plans "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_campaign_target_plans")
    op.execute("ALTER TABLE crm_marketing_campaign_target_plans NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaign_target_plans DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_marketing_campaign_target_plans")
