"""Store a key ID for keyed event envelope digests.

Revision ID: 20261018_14
Revises: 20261018_13
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_14"
down_revision = "20261018_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_event_inbox",
        sa.Column("event_digest_key_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_event_inbox", "event_digest_key_id")
