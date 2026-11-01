"""Add net commerce target to campaign target plans."""

from alembic import op
import sqlalchemy as sa

revision = "20261027_74"
down_revision = "20261027_73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_target_plans",
        sa.Column("min_net_paid_to_spend", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "crm_marketing_campaign_target_plans",
        sa.Column("net_paid_to_spend_currency", sa.String(3), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_target_plans_net_paid_to_spend_pair",
        "crm_marketing_campaign_target_plans",
        "(min_net_paid_to_spend IS NULL AND net_paid_to_spend_currency IS NULL) OR "
        "(min_net_paid_to_spend IS NOT NULL AND min_net_paid_to_spend >= 0 AND "
        "length(net_paid_to_spend_currency) = 3 AND net_paid_to_spend_currency = upper(net_paid_to_spend_currency) "
        "AND net_paid_to_spend_currency ~ '^[A-Z][A-Z][A-Z]')",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_target_plans_has_goal",
        "crm_marketing_campaign_target_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_target_plans_has_goal",
        "crm_marketing_campaign_target_plans",
        "impressions_target IS NOT NULL OR clicks_target IS NOT NULL OR leads_target IS NOT NULL OR "
        "conversions_target IS NOT NULL OR max_spend_amount IS NOT NULL OR max_cpl_amount IS NOT NULL OR "
        "max_cost_per_conversion_amount IS NOT NULL OR min_roas IS NOT NULL OR min_net_paid_to_spend IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_target_plans_has_goal",
        "crm_marketing_campaign_target_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_target_plans_has_goal",
        "crm_marketing_campaign_target_plans",
        "impressions_target IS NOT NULL OR clicks_target IS NOT NULL OR leads_target IS NOT NULL OR "
        "conversions_target IS NOT NULL OR max_spend_amount IS NOT NULL OR max_cpl_amount IS NOT NULL OR "
        "max_cost_per_conversion_amount IS NOT NULL OR min_roas IS NOT NULL",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_target_plans_net_paid_to_spend_pair",
        "crm_marketing_campaign_target_plans",
        type_="check",
    )
    op.drop_column("crm_marketing_campaign_target_plans", "net_paid_to_spend_currency")
    op.drop_column("crm_marketing_campaign_target_plans", "min_net_paid_to_spend")
