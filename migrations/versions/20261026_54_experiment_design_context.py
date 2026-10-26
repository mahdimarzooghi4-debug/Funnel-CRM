"""Record allocation method and known limitations for campaign experiments."""
from alembic import op
import sqlalchemy as sa

revision = "20261026_54"
down_revision = "20261026_53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaign_experiments",
        sa.Column("allocation_method", sa.String(250), nullable=False,
                  server_default=sa.text("'unspecified'")),
    )
    op.add_column(
        "crm_marketing_campaign_experiments",
        sa.Column("known_limitations", sa.String(1000), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_allocation_method",
        "crm_marketing_campaign_experiments",
        "length(trim(allocation_method)) BETWEEN 1 AND 250",
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaign_experiments_known_limitations",
        "crm_marketing_campaign_experiments",
        "known_limitations IS NULL OR length(trim(known_limitations)) BETWEEN 1 AND 1000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_known_limitations",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.drop_constraint(
        "ck_crm_marketing_campaign_experiments_allocation_method",
        "crm_marketing_campaign_experiments", type_="check",
    )
    op.drop_column("crm_marketing_campaign_experiments", "known_limitations")
    op.drop_column("crm_marketing_campaign_experiments", "allocation_method")
