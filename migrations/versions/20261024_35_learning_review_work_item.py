"""Link CRM work items to marketing learning reviews."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261024_35"
down_revision = "20261024_34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_work_items",
        sa.Column("source_learning_review_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_crm_work_items_learning_review_same_tenant",
        "crm_work_items", "crm_marketing_learning_reviews",
        ["tenant_id", "source_learning_review_id"], ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_crm_work_items_source_learning_review",
        "crm_work_items", ["tenant_id", "source_learning_review_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_crm_work_items_source_learning_review", "crm_work_items", type_="unique")
    op.drop_constraint("fk_crm_work_items_learning_review_same_tenant", "crm_work_items", type_="foreignkey")
    op.drop_column("crm_work_items", "source_learning_review_id")
