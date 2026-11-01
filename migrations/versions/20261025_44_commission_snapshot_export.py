"""Add explicit permission for exporting commission snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "20261025_44"
down_revision = "20261025_43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    permissions = sa.table(
        "permission_definitions",
        sa.column("key", sa.String(160)),
        sa.column("description", sa.String(500)),
    )
    op.bulk_insert(permissions, [{
        "key": "crm.commission:export",
        "description": "Export commission calculation snapshots in authorized organization scopes",
    }])


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_key = 'crm.commission:export'")
    op.execute("DELETE FROM permission_definitions WHERE key = 'crm.commission:export'")
