"""Add effective dates to commission plan versions."""
from alembic import op
import sqlalchemy as sa

revision = "20261025_43"
down_revision = "20261025_42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("crm_commission_plans", "crm_commission_plan_versions"):
        op.add_column(table, sa.Column("effective_start", sa.Date(), nullable=True))
        op.add_column(table, sa.Column("effective_end", sa.Date(), nullable=True))
        op.create_check_constraint(
            f"ck_{table}_effective_window",
            table,
            "effective_start IS NULL OR effective_end IS NULL OR effective_start <= effective_end",
        )


def downgrade() -> None:
    for table in ("crm_commission_plan_versions", "crm_commission_plans"):
        op.drop_constraint(f"ck_{table}_effective_window", table, type_="check")
        op.drop_column(table, "effective_end")
        op.drop_column(table, "effective_start")
