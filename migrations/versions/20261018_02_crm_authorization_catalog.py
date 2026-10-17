"""Seed the action-level CRM authorization catalog.

Revision ID: 20261018_02
Revises: 20261018_01
"""

from alembic import op

revision = "20261018_02"
down_revision = "20261018_01"
branch_labels = None
depends_on = None

CRM_PERMISSIONS = (
    ("crm.settings:manage", "Manage CRM workspace settings"),
    ("crm.pipeline:manage", "Manage CRM pipelines and stages"),
    ("crm.custom_field:manage", "Manage CRM custom field definitions"),
    ("crm.profile:view", "View CRM customer profiles"),
    ("crm.profile:create", "Create CRM customer profiles"),
    ("crm.profile:update", "Update CRM customer profiles"),
    ("crm.profile:archive", "Archive CRM customer profiles"),
    ("crm.profile:export", "Export CRM customer profile data"),
)


def upgrade() -> None:
    permission_values = ",\n".join(
        f"('{key}', '{description}')" for key, description in CRM_PERMISSIONS
    )
    op.execute(
        f"""
        INSERT INTO permission_definitions (key, description)
        VALUES {permission_values}
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key, _description in CRM_PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_key IN ({keys})
        """
    )
    op.execute(
        f"""
        DELETE FROM permission_definitions
        WHERE key IN ({keys})
        """
    )
