"""Add campaign attribution to customer activity records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_26"
down_revision = "20261018_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_customer_activities",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_crm_customer_activities_campaign_same_tenant",
        "crm_customer_activities",
        "crm_marketing_campaigns",
        ["tenant_id", "campaign_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_crm_customer_activities_tenant_campaign_time",
        "crm_customer_activities",
        ["tenant_id", "campaign_id", "occurred_at"],
        unique=False,
        postgresql_where=sa.text("campaign_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_customer_activities_tenant_campaign_time",
        table_name="crm_customer_activities",
    )
    op.drop_constraint(
        "fk_crm_customer_activities_campaign_same_tenant",
        "crm_customer_activities",
        type_="foreignkey",
    )
    op.drop_column("crm_customer_activities", "campaign_id")
