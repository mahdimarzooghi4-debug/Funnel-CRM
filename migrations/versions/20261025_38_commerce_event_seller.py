"""Capture optional seller attribution on product commerce events."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_38"
down_revision = "20261025_37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_product_commerce_events",
        sa.Column("seller_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_crm_product_commerce_events_seller_same_tenant",
        "crm_product_commerce_events", "workspace_memberships",
        ["tenant_id", "seller_membership_id"], ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_crm_product_commerce_events_tenant_seller_time",
        "crm_product_commerce_events",
        ["tenant_id", "seller_membership_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_product_commerce_events_tenant_seller_time", table_name="crm_product_commerce_events")
    op.drop_constraint("fk_crm_product_commerce_events_seller_same_tenant", "crm_product_commerce_events", type_="foreignkey")
    op.drop_column("crm_product_commerce_events", "seller_membership_id")
