"""Persist direct lineage from a follow-up task to its source outcome."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_37"
down_revision = "20261025_36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_work_items",
        sa.Column("source_outcome_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_crm_work_items_outcome_same_tenant",
        "crm_work_items", "crm_work_item_outcomes",
        ["tenant_id", "source_outcome_id"], ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_crm_work_items_source_outcome",
        "crm_work_items", ["tenant_id", "source_outcome_id"],
    )

def downgrade() -> None:
    op.drop_constraint("uq_crm_work_items_source_outcome", "crm_work_items", type_="unique")
    op.drop_constraint("fk_crm_work_items_outcome_same_tenant", "crm_work_items", type_="foreignkey")
    op.drop_column("crm_work_items", "source_outcome_id")
