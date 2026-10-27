"""Allow paid-order count and paid amount as experiment metrics."""
from alembic import op

revision = "20261027_63"
down_revision = "20261027_62"
branch_labels = None
depends_on = None

OLD_METRICS = "'impressions', 'clicks', 'leads', 'conversions', 'return_count', 'refunded_order_count', 'refunded_order_rate_percent', 'click_through_rate_percent', 'conversion_rate_per_click_percent', 'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost', 'refunded_amount', 'refund_amount'"
NEW_METRICS = "'impressions', 'clicks', 'leads', 'conversions', 'return_count', 'paid_order_count', 'refunded_order_count', 'refunded_order_rate_percent', 'click_through_rate_percent', 'conversion_rate_per_click_percent', 'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost', 'paid_amount', 'refunded_amount', 'refund_amount'"
OLD_CURRENCIES = "'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost', 'refunded_amount', 'refund_amount'"
NEW_CURRENCIES = "'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost', 'paid_amount', 'refunded_amount', 'refund_amount'"


def _replace(metrics: str, currencies: str) -> None:
    op.drop_constraint("ck_crm_marketing_campaign_experiments_metric", "crm_marketing_campaign_experiments", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_metric", "crm_marketing_campaign_experiments",
        f"primary_metric IN ({metrics})",
    )
    op.drop_constraint("ck_crm_marketing_campaign_experiments_currency", "crm_marketing_campaign_experiments", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_currency", "crm_marketing_campaign_experiments",
        f"(primary_metric IN ({currencies}) AND currency IS NOT NULL AND length(currency) = 3 "
        "AND currency = upper(currency) AND currency ~ '^[A-Z][A-Z][A-Z]') OR "
        f"(primary_metric NOT IN ({currencies}) AND currency IS NULL)",
    )


def upgrade() -> None:
    _replace(NEW_METRICS, NEW_CURRENCIES)


def downgrade() -> None:
    _replace(OLD_METRICS, OLD_CURRENCIES)
