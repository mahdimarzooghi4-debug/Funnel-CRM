"""Allow paid-order refund match rate as an experiment metric."""
from alembic import op

revision = "20261027_69"
down_revision = "20261027_68"
branch_labels = None
depends_on = None

OLD_METRICS = "'impressions', 'clicks', 'leads', 'conversions', 'return_count', 'paid_order_count', 'refunded_order_count', 'refunded_order_rate_percent', 'matched_refund_order_rate_percent', 'unmatched_refund_order_count', 'paid_order_without_refund_count', 'click_through_rate_percent', 'conversion_rate_per_click_percent', 'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost', 'paid_amount', 'average_paid_order_value', 'average_refund_per_order', 'refund_to_paid_amount_percent', 'refunded_amount', 'refund_amount'"
NEW_METRICS = "'impressions', 'clicks', 'leads', 'conversions', 'return_count', 'paid_order_count', 'refunded_order_count', 'refunded_order_rate_percent', 'matched_refund_order_rate_percent', 'paid_order_refund_match_rate_percent', 'unmatched_refund_order_count', 'paid_order_without_refund_count', 'click_through_rate_percent', 'conversion_rate_per_click_percent', 'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost', 'paid_amount', 'average_paid_order_value', 'average_refund_per_order', 'refund_to_paid_amount_percent', 'refunded_amount', 'refund_amount'"


def _replace(metrics: str) -> None:
    op.drop_constraint("ck_crm_marketing_campaign_experiments_metric", "crm_marketing_campaign_experiments", type_="check")
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_metric", "crm_marketing_campaign_experiments",
        f"primary_metric IN ({metrics})",
    )


def upgrade() -> None:
    _replace(NEW_METRICS)


def downgrade() -> None:
    _replace(OLD_METRICS)
