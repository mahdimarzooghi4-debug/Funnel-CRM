"""Link immutable opportunity offer draft revisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_49"
down_revision = "20261025_48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_opportunity_offer_drafts", sa.Column(
        "revision_number", sa.Integer(), server_default=sa.text("1"), nullable=False,
    ))
    op.add_column("crm_opportunity_offer_drafts", sa.Column(
        "previous_revision_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_check_constraint(
        "ck_crm_opportunity_offer_drafts_revision_number",
        "crm_opportunity_offer_drafts", "revision_number >= 1",
    )
    op.create_unique_constraint(
        "uq_crm_opportunity_offer_drafts_previous_revision",
        "crm_opportunity_offer_drafts", ["tenant_id", "previous_revision_id"],
    )
    op.create_foreign_key(
        "fk_crm_opportunity_offer_drafts_previous_revision",
        "crm_opportunity_offer_drafts", "crm_opportunity_offer_drafts",
        ["tenant_id", "previous_revision_id"], ["tenant_id", "id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_crm_opportunity_offer_drafts_previous_revision", "crm_opportunity_offer_drafts", type_="foreignkey")
    op.drop_constraint("uq_crm_opportunity_offer_drafts_previous_revision", "crm_opportunity_offer_drafts", type_="unique")
    op.drop_constraint("ck_crm_opportunity_offer_drafts_revision_number", "crm_opportunity_offer_drafts", type_="check")
    op.drop_column("crm_opportunity_offer_drafts", "previous_revision_id")
    op.drop_column("crm_opportunity_offer_drafts", "revision_number")
