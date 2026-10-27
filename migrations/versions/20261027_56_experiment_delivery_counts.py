"""Capture assigned audience and campaign exposures in daily measurements."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_56"
down_revision = "20261027_55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_measurements",
        sa.Column("assigned_count", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "crm_marketing_campaign_measurements",
        sa.Column("exposure_count", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_measurements_delivery_counts",
        "crm_marketing_campaign_measurements",
        "(assigned_count IS NULL OR assigned_count >= 0) AND "
        "(exposure_count IS NULL OR exposure_count >= 0)",
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
        "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL",
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
        "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_measurements_delivery_counts",
        "crm_marketing_campaign_measurements", type_="check",
    )
    op.drop_column("crm_marketing_campaign_measurements", "exposure_count")
    op.drop_column("crm_marketing_campaign_measurements", "assigned_count")
