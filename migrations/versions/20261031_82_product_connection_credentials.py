"""Allow short-lived overlap when rotating product connection credentials.

Revision ID: 20261031_82
Revises: 20261031_81
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_82"
down_revision = "20261031_81"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_connection_credentials",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_digest", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(credential_digest) = 32",
            name="ck_product_connection_credentials_digest",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["product_connections.tenant_id", "product_connections.id"],
            name="fk_product_connection_credentials_connection",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "credential_id"),
    )
    op.create_index(
        "ix_product_connection_credentials_connection",
        "product_connection_credentials",
        ["tenant_id", "connection_id", "created_at"],
    )
    op.execute(
        """
        INSERT INTO product_connection_credentials
            (tenant_id, credential_id, connection_id, credential_digest, created_at, revoked_at)
        SELECT tenant_id, credential_id, id, credential_digest, created_at, revoked_at
        FROM product_connections
        """
    )
    op.execute(
        "ALTER TABLE product_connection_credentials ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE product_connection_credentials FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON product_connection_credentials
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_connection_credentials_connection",
        table_name="product_connection_credentials",
    )
    op.drop_table("product_connection_credentials")
