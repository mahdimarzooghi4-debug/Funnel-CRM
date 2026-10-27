"""Record daily discount and incentive cost separately from campaign spend."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_57"
down_revision = "20261027_56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_measurements",
        sa.Column("incentive_cost_amount", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "crm_marketing_campaign_measurements",
        sa.Column("incentive_cost_currency", sa.String(length=3), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_incentive_cost",
        "crm_marketing_campaign_measurements",
        "(incentive_cost_amount IS NULL AND incentive_cost_currency IS NULL) OR "
        "(incentive_cost_amount IS NOT NULL AND incentive_cost_amount >= 0 "
        "AND length(incentive_cost_currency) = 3 "
        "AND incentive_cost_currency = upper(incentive_cost_currency) "
        "AND incentive_cost_currency ~ '^[A-Z][A-Z][A-Z]')",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_measurements_has_observation",
        "crm_marketing_campaign_measurements", type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_has_observation",
        "crm_marketing_campaign_measurements",
        "impressions IS NOT NULL OR reach IS NOT NULL OR clicks IS NOT NULL OR "
        "responses IS NOT NULL OR leads IS NOT NULL OR conversions IS NOT NULL OR "
        "assigned_count IS NOT NULL OR exposure_count IS NOT NULL OR "
        "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL OR "
        "incentive_cost_amount IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_measurements_has_observation",
        "crm_marketing_campaign_measurements", type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_has_observation",
        "crm_marketing_campaign_measurements",
        "impressions IS NOT NULL OR reach IS NOT NULL OR clicks IS NOT NULL OR "
        "responses IS NOT NULL OR leads IS NOT NULL OR conversions IS NOT NULL OR "
        "assigned_count IS NOT NULL OR exposure_count IS NOT NULL OR "
        "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_measurements_incentive_cost",
        "crm_marketing_campaign_measurements", type_="check",
    )
    op.drop_column("crm_marketing_campaign_measurements", "incentive_cost_currency")
    op.drop_column("crm_marketing_campaign_measurements", "incentive_cost_amount")
