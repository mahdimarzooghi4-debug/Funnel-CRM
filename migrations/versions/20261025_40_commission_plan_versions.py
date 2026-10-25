"""Record commission plan versions in mutable plans and immutable calculations."""
from alembic import op
import sqlalchemy as sa

revision = "20261025_40"
down_revision = "20261025_39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_commission_plans",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        "ck_crm_commission_plans_version_positive",
        "crm_commission_plans", "version >= 1",
    )
    op.add_column(
        "crm_commission_calculations",
        sa.Column("plan_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        "ck_crm_commission_calculations_plan_version_positive",
        "crm_commission_calculations", "plan_version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_commission_calculations_plan_version_positive",
        "crm_commission_calculations", type_="check",
    )
    op.drop_column("crm_commission_calculations", "plan_version")
    op.drop_constraint(
        "ck_crm_commission_plans_version_positive",
        "crm_commission_plans", type_="check",
    )
    op.drop_column("crm_commission_plans", "version")
