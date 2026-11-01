"""Allow campaign incentive cost as an experiment metric."""
from alembic import op

revision = "20261027_58"
down_revision = "20261027_57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_metric",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_metric",
        "crm_marketing_campaign_experiments",
        "primary_metric IN ('impressions', 'clicks', 'leads', 'conversions', "
        "'click_through_rate_percent', 'conversion_rate_per_click_percent', "
        "'cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost')",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_currency",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_currency",
        "crm_marketing_campaign_experiments",
        "(primary_metric IN ('cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost') "
        "AND currency IS NOT NULL AND length(currency) = 3 AND currency = upper(currency) "
        "AND currency ~ '^[A-Z][A-Z][A-Z]') OR "
        "(primary_metric NOT IN ('cost_per_lead', 'cost_per_conversion', 'roas', 'incentive_cost') "
        "AND currency IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_currency",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_currency",
        "crm_marketing_campaign_experiments",
        "(primary_metric IN ('cost_per_lead', 'cost_per_conversion', 'roas') "
        "AND currency IS NOT NULL AND length(currency) = 3 AND currency = upper(currency) "
        "AND currency ~ '^[A-Z][A-Z][A-Z]') OR "
        "(primary_metric NOT IN ('cost_per_lead', 'cost_per_conversion', 'roas') AND currency IS NULL)",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_metric",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_metric",
        "crm_marketing_campaign_experiments",
        "primary_metric IN ('impressions', 'clicks', 'leads', 'conversions', "
        "'click_through_rate_percent', 'conversion_rate_per_click_percent', "
        "'cost_per_lead', 'cost_per_conversion', 'roas')",
    )
