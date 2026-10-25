"""Add idempotency keys for commission calculation requests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_42"
down_revision = "20261025_41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_commission_calculations",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_crm_commission_calculations_request",
        "crm_commission_calculations", ["tenant_id", "plan_id", "request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_crm_commission_calculations_request",
        "crm_commission_calculations", type_="unique",
    )
    op.drop_column("crm_commission_calculations", "request_id")
