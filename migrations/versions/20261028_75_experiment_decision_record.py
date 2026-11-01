"""Persist the manager's final decision and next action for a campaign experiment."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261028_75"
down_revision = "20261027_74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_experiments",
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_decision",
        "crm_marketing_campaign_experiments",
        "decision IS NULL OR (jsonb_typeof(decision) = 'object' AND octet_length(decision::text) <= 8192)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_decision",
        "crm_marketing_campaign_experiments",
        type_="check",
    )
    op.drop_column("crm_marketing_campaign_experiments", "decision")
