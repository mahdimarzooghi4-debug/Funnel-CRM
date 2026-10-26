"""Store configured guardrail metrics for campaign experiments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261026_53"
down_revision = "20261025_52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_experiments",
        sa.Column("guardrail_metrics", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_guardrails_array",
        "crm_marketing_campaign_experiments",
        "jsonb_typeof(guardrail_metrics) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_guardrails_array",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.drop_column("crm_marketing_campaign_experiments", "guardrail_metrics")
