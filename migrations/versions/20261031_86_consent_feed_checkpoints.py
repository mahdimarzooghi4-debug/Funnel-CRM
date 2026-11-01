"""Track acknowledged product consent feed cursors.

Revision ID: 20261031_86
Revises: 20261031_85
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_86"
down_revision = "20261031_85"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_consent_product_sync_checkpoints",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_product", sa.String(length=80), nullable=False),
        sa.Column(
            "last_acked_sequence",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_acked_sequence >= 0",
            name="ck_crm_consent_sync_checkpoint_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_consent_sync_checkpoint_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "recipient_product"),
    )
    op.execute(
        "ALTER TABLE crm_consent_product_sync_checkpoints ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY crm_consent_product_sync_checkpoints_tenant_isolation
        ON crm_consent_product_sync_checkpoints
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.drop_table("crm_consent_product_sync_checkpoints")
