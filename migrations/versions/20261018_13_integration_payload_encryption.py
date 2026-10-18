"""Store new product event inbox payloads as authenticated ciphertext.

Revision ID: 20261018_13
Revises: 20261018_12
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_13"
down_revision = "20261018_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_event_inbox",
        sa.Column("payload_key_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "integration_event_inbox",
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=True),
    )
    op.create_check_constraint(
        "ck_integration_event_inbox_payload_cipher_pair",
        "integration_event_inbox",
        "(payload_key_id IS NULL) = (encrypted_payload IS NULL)",
    )
    op.create_check_constraint(
        "ck_integration_event_inbox_cipher_has_empty_legacy_payload",
        "integration_event_inbox",
        "payload_key_id IS NULL OR payload = '{}'::jsonb",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_integration_event_inbox_cipher_has_empty_legacy_payload",
        "integration_event_inbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_integration_event_inbox_payload_cipher_pair",
        "integration_event_inbox",
        type_="check",
    )
    op.drop_column("integration_event_inbox", "encrypted_payload")
    op.drop_column("integration_event_inbox", "payload_key_id")
