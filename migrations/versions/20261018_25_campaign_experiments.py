"""Add marketing campaign experiments and variant assignments.

Revision ID: 20261018_25
Revises: 20261018_24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_25"
down_revision = "20261018_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_campaign_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("hypothesis", sa.String(1000), nullable=False),
        sa.Column("primary_metric", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_experiments_tenant_id"),
        sa.UniqueConstraint("tenant_id", "organization_unit_id", "id",
                            name="uq_crm_marketing_campaign_experiments_tenant_org_id"),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160 AND length(trim(hypothesis)) BETWEEN 1 AND 1000",
            name="ck_crm_marketing_campaign_experiments_text"),
        sa.CheckConstraint("period_start <= period_end AND period_end - period_start < 366",
                           name="ck_crm_marketing_campaign_experiments_period"),
        sa.CheckConstraint(
            "primary_metric IN ('impressions', 'clicks', 'leads', 'conversions', "
            "'click_through_rate_percent', 'conversion_rate_per_click_percent', "
            "'cost_per_lead', 'cost_per_conversion', 'roas')",
            name="ck_crm_marketing_campaign_experiments_metric"),
        sa.CheckConstraint(
            "(primary_metric IN ('cost_per_lead', 'cost_per_conversion', 'roas') "
            "AND currency IS NOT NULL AND length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z][A-Z][A-Z]') OR "
            "(primary_metric NOT IN ('cost_per_lead', 'cost_per_conversion', 'roas') AND currency IS NULL)",
            name="ck_crm_marketing_campaign_experiments_currency"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_experiments_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_experiments_org_same_tenant", ondelete="RESTRICT"),
        sa.Index("ix_crm_marketing_campaign_experiments_tenant_org_period",
                 "tenant_id", "organization_unit_id", "period_start", "period_end"),
    )
    op.create_table(
        "crm_marketing_campaign_experiment_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("is_control", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "experiment_id", "campaign_id",
                            name="uq_crm_marketing_campaign_experiment_variants_campaign"),
        sa.CheckConstraint("length(trim(label)) BETWEEN 1 AND 80",
                           name="ck_crm_marketing_campaign_experiment_variants_label"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_experiment_variants_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "experiment_id"],
            ["crm_marketing_campaign_experiments.tenant_id",
             "crm_marketing_campaign_experiments.organization_unit_id",
             "crm_marketing_campaign_experiments.id"],
            name="fk_crm_marketing_campaign_experiment_variants_experiment_same_org",
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_experiment_variants_campaign_same_org",
            ondelete="RESTRICT"),
        sa.Index(
            "uq_crm_marketing_campaign_experiment_variants_one_control",
            "tenant_id", "experiment_id", unique=True,
            postgresql_where=sa.text("is_control"),
        ),
        sa.Index("ix_crm_marketing_campaign_experiment_variants_tenant_campaign",
                 "tenant_id", "campaign_id"),
    )
    for table in (
        "crm_marketing_campaign_experiments",
        "crm_marketing_campaign_experiment_variants",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    for table in (
        "crm_marketing_campaign_experiment_variants",
        "crm_marketing_campaign_experiments",
    ):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_marketing_campaign_experiment_variants")
    op.drop_table("crm_marketing_campaign_experiments")
