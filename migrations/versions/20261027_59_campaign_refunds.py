"""Record returned-order counts and refunded amounts in campaign measurements."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_59"
down_revision = "20261027_58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_marketing_campaign_measurements", sa.Column("return_count", sa.BigInteger(), nullable=True))
    op.add_column("crm_marketing_campaign_measurements", sa.Column("refunded_amount", sa.Numeric(20, 6), nullable=True))
    op.add_column("crm_marketing_campaign_measurements", sa.Column("refunded_currency", sa.String(length=3), nullable=True))
    op.drop_constraint("ck_crm_marketing_campaign_measurements_counts", "crm_marketing_campaign_measurements", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_counts", "crm_marketing_campaign_measurements",
        "(impressions IS NULL OR impressions >= 0) AND (reach IS NULL OR reach >= 0) AND "
        "(clicks IS NULL OR clicks >= 0) AND (responses IS NULL OR responses >= 0) AND "
        "(leads IS NULL OR leads >= 0) AND (conversions IS NULL OR conversions >= 0) AND "
        "(assigned_count IS NULL OR assigned_count >= 0) AND (exposure_count IS NULL OR exposure_count >= 0) AND "
        "(return_count IS NULL OR return_count >= 0)",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_refunded_amount", "crm_marketing_campaign_measurements",
        "(refunded_amount IS NULL AND refunded_currency IS NULL) OR "
        "(refunded_amount IS NOT NULL AND refunded_amount >= 0 AND length(refunded_currency) = 3 "
        "AND refunded_currency = upper(refunded_currency) AND refunded_currency ~ '^[A-Z][A-Z][A-Z]')",
    )
    op.drop_constraint("ck_crm_marketing_campaign_measurements_has_observation", "crm_marketing_campaign_measurements", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_has_observation",
        "crm_marketing_campaign_measurements",
        "impressions IS NOT NULL OR reach IS NOT NULL OR clicks IS NOT NULL OR responses IS NOT NULL OR "
        "leads IS NOT NULL OR conversions IS NOT NULL OR assigned_count IS NOT NULL OR exposure_count IS NOT NULL OR "
        "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL OR incentive_cost_amount IS NOT NULL OR "
        "return_count IS NOT NULL OR refunded_amount IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_crm_marketing_campaign_measurements_has_observation", "crm_marketing_campaign_measurements", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_has_observation",
        "crm_marketing_campaign_measurements",
        "impressions IS NOT NULL OR reach IS NOT NULL OR clicks IS NOT NULL OR responses IS NOT NULL OR "
        "leads IS NOT NULL OR conversions IS NOT NULL OR assigned_count IS NOT NULL OR exposure_count IS NOT NULL OR "
        "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL OR incentive_cost_amount IS NOT NULL",
    )
    op.drop_constraint("ck_crm_marketing_campaign_measurements_refunded_amount", "crm_marketing_campaign_measurements", type_="check")
    op.drop_constraint("ck_crm_marketing_campaign_measurements_counts", "crm_marketing_campaign_measurements", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_counts", "crm_marketing_campaign_measurements",
        "(impressions IS NULL OR impressions >= 0) AND (reach IS NULL OR reach >= 0) AND "
        "(clicks IS NULL OR clicks >= 0) AND (responses IS NULL OR responses >= 0) AND "
        "(leads IS NULL OR leads >= 0) AND (conversions IS NULL OR conversions >= 0) AND "
        "(assigned_count IS NULL OR assigned_count >= 0) AND (exposure_count IS NULL OR exposure_count >= 0)",
    )
    op.drop_column("crm_marketing_campaign_measurements", "refunded_currency")
    op.drop_column("crm_marketing_campaign_measurements", "refunded_amount")
    op.drop_column("crm_marketing_campaign_measurements", "return_count")
