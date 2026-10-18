"""Add explicit campaign budget planning fields and constraints.

Revision ID: 20261018_20
Revises: 20261018_19
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_20"
down_revision = "20261018_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaigns",
        sa.Column("planned_budget_amount", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "crm_marketing_campaigns",
        sa.Column("planned_budget_currency", sa.String(3), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaigns_budget_pair",
        "crm_marketing_campaigns",
        "("
        "(planned_budget_amount IS NULL AND planned_budget_currency IS NULL) OR "
        "(planned_budget_amount IS NOT NULL AND planned_budget_amount >= 0 "
        "AND planned_budget_currency ~ '^[A-Z]{3}$')"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaigns_budget_pair",
        "crm_marketing_campaigns",
        type_="check",
    )
    op.drop_column("crm_marketing_campaigns", "planned_budget_currency")
    op.drop_column("crm_marketing_campaigns", "planned_budget_amount")
