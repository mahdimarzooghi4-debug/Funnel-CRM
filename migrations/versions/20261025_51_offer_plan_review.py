"""Add explicit review decisions to marketing offer plans."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_51"
down_revision = "20261025_50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_crm_marketing_offer_plans_status", "crm_marketing_offer_plans", type_="check")
    op.alter_column("crm_marketing_offer_plans", "status", existing_type=sa.String(16), type_=sa.String(24), existing_nullable=False, existing_server_default=sa.text("'draft'"))
    op.add_column("crm_marketing_offer_plans", sa.Column("review_note", sa.String(2000), nullable=True))
    op.add_column("crm_marketing_offer_plans", sa.Column("reviewed_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("crm_marketing_offer_plans", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_crm_marketing_offer_plans_status", "crm_marketing_offer_plans",
        "status IN ('draft', 'changes_requested', 'approved')",
    )
    op.create_check_constraint(
        "ck_crm_marketing_offer_plans_review_state", "crm_marketing_offer_plans",
        "(status = 'draft' AND reviewed_by_membership_id IS NULL AND reviewed_at IS NULL AND review_note IS NULL) OR "
        "(status IN ('changes_requested', 'approved') AND reviewed_by_membership_id IS NOT NULL AND reviewed_at IS NOT NULL AND review_note IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_crm_marketing_offer_plans_reviewer", "crm_marketing_offer_plans", "workspace_memberships",
        ["tenant_id", "reviewed_by_membership_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )
    permissions = sa.table("permission_definitions", sa.column("key", sa.String(160)), sa.column("description", sa.String(500)))
    op.bulk_insert(permissions, [
        {"key": "crm.offer_plan:approve", "description": "Review and decide marketing offer plan drafts in authorized scopes"},
    ])


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_key = 'crm.offer_plan:approve'")
    op.execute("DELETE FROM permission_definitions WHERE key = 'crm.offer_plan:approve'")
    op.drop_constraint("fk_crm_marketing_offer_plans_reviewer", "crm_marketing_offer_plans", type_="foreignkey")
    op.drop_constraint("ck_crm_marketing_offer_plans_review_state", "crm_marketing_offer_plans", type_="check")
    op.drop_constraint("ck_crm_marketing_offer_plans_status", "crm_marketing_offer_plans", type_="check")
    op.execute("UPDATE crm_marketing_offer_plans SET status = 'draft', review_note = NULL, reviewed_by_membership_id = NULL, reviewed_at = NULL")
    op.create_check_constraint("ck_crm_marketing_offer_plans_status", "crm_marketing_offer_plans", "status = 'draft'")
    op.alter_column("crm_marketing_offer_plans", "status", existing_type=sa.String(24), type_=sa.String(16), existing_nullable=False, existing_server_default=sa.text("'draft'"))
    op.drop_column("crm_marketing_offer_plans", "reviewed_at")
    op.drop_column("crm_marketing_offer_plans", "reviewed_by_membership_id")
    op.drop_column("crm_marketing_offer_plans", "review_note")
