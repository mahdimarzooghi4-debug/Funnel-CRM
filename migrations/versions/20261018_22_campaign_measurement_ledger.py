"""Add dated observed campaign measurement records.

Revision ID: 20261018_22
Revises: 20261018_21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_22"
down_revision = "20261018_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_campaign_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("source_label", sa.String(120), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=True),
        sa.Column("reach", sa.BigInteger(), nullable=True),
        sa.Column("clicks", sa.BigInteger(), nullable=True),
        sa.Column("responses", sa.BigInteger(), nullable=True),
        sa.Column("leads", sa.BigInteger(), nullable=True),
        sa.Column("conversions", sa.BigInteger(), nullable=True),
        sa.Column("actual_spend_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("actual_spend_currency", sa.String(3), nullable=True),
        sa.Column("attributed_revenue_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("attributed_revenue_currency", sa.String(3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_measurements_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "campaign_id", "measured_on",
            name="uq_crm_marketing_campaign_measurements_campaign_day",
        ),
        sa.CheckConstraint(
            "length(trim(source_label)) BETWEEN 1 AND 120",
            name="ck_crm_marketing_campaign_measurements_source",
        ),
        sa.CheckConstraint(
            "(impressions IS NULL OR impressions >= 0) AND "
            "(reach IS NULL OR reach >= 0) AND "
            "(clicks IS NULL OR clicks >= 0) AND "
            "(responses IS NULL OR responses >= 0) AND "
            "(leads IS NULL OR leads >= 0) AND "
            "(conversions IS NULL OR conversions >= 0)",
            name="ck_crm_marketing_campaign_measurements_counts",
        ),
        sa.CheckConstraint(
            "(actual_spend_amount IS NULL AND actual_spend_currency IS NULL) OR "
            "(actual_spend_amount IS NOT NULL AND actual_spend_amount >= 0 "
            "AND length(actual_spend_currency) = 3 "
            "AND actual_spend_currency = upper(actual_spend_currency) "
            "AND actual_spend_currency ~ '^[A-Z]{3}$')",
            name="ck_crm_marketing_campaign_measurements_spend",
        ),
        sa.CheckConstraint(
            "(attributed_revenue_amount IS NULL AND attributed_revenue_currency IS NULL) OR "
            "(attributed_revenue_amount IS NOT NULL AND attributed_revenue_amount >= 0 "
            "AND length(attributed_revenue_currency) = 3 "
            "AND attributed_revenue_currency = upper(attributed_revenue_currency) "
            "AND attributed_revenue_currency ~ '^[A-Z]{3}$')",
            name="ck_crm_marketing_campaign_measurements_revenue",
        ),
        sa.CheckConstraint(
            "impressions IS NOT NULL OR reach IS NOT NULL OR clicks IS NOT NULL OR "
            "responses IS NOT NULL OR leads IS NOT NULL OR conversions IS NOT NULL OR "
            "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL",
            name="ck_crm_marketing_campaign_measurements_has_observation",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_measurements_workspace", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_measurements_org_same_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_measurements_campaign_same_org", ondelete="CASCADE",
        ),
        sa.Index(
            "ix_crm_marketing_campaign_measurements_tenant_org_day",
            "tenant_id", "organization_unit_id", "measured_on",
        ),
    )
    op.execute("ALTER TABLE crm_marketing_campaign_measurements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaign_measurements FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_marketing_campaign_measurements "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_campaign_measurements")
    op.execute("ALTER TABLE crm_marketing_campaign_measurements NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_campaign_measurements DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_marketing_campaign_measurements")
