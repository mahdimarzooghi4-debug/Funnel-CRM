"""Index manager action worklists and analytics by creator and assignee.

Revision ID: 20261101_89
Revises: 20261101_88
"""

from alembic import op

revision = "20261101_89"
down_revision = "20261101_88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_crm_dashboard_actions_creator_status_due",
        "crm_marketing_dashboard_actions",
        ["tenant_id", "creator_identity_id", "status", "due_on"],
    )
    op.create_index(
        "ix_crm_dashboard_actions_assignee_status_due",
        "crm_marketing_dashboard_actions",
        ["tenant_id", "assigned_membership_id", "status", "due_on"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_dashboard_actions_assignee_status_due",
        table_name="crm_marketing_dashboard_actions",
    )
    op.drop_index(
        "ix_crm_dashboard_actions_creator_status_due",
        table_name="crm_marketing_dashboard_actions",
    )
