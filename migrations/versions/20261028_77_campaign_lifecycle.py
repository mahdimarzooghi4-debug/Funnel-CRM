"""Add campaign lifecycle states."""
from alembic import op

revision = "20261028_77"
down_revision = "20261028_76"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_crm_marketing_campaigns_status", "crm_marketing_campaigns", type_="check")
    op.create_check_constraint("ck_crm_marketing_campaigns_status", "crm_marketing_campaigns", "status IN ('draft', 'scheduled', 'active', 'paused', 'completed', 'archived')")


def downgrade() -> None:
    op.execute("UPDATE crm_marketing_campaigns SET status = CASE WHEN status IN ('scheduled', 'active', 'paused') THEN 'draft' WHEN status = 'completed' THEN 'archived' ELSE status END")
    op.drop_constraint("ck_crm_marketing_campaigns_status", "crm_marketing_campaigns", type_="check")
    op.create_check_constraint("ck_crm_marketing_campaigns_status", "crm_marketing_campaigns", "status IN ('draft', 'archived')")
