"""Snapshot the shared audience segment used by a campaign experiment."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261027_55"
down_revision = "20261026_54"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_experiments",
        sa.Column("audience_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_audience_snapshot",
        "crm_marketing_campaign_experiments",
        "audience_snapshot IS NULL OR (jsonb_typeof(audience_snapshot) = 'object' "
        "AND octet_length(audience_snapshot::text) <= 8192)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_audience_snapshot",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.drop_column("crm_marketing_campaign_experiments", "audience_snapshot")
