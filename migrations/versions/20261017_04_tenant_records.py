"""Add the tenant-owned record anchor.

Revision ID: 20261017_04
Revises: 20261017_03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261017_04"
down_revision = "20261017_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(trim(record_type)) > 0",
            name="ck_tenant_records_type_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_tenant_records_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_tenant_records_org_same_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_records"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tenant_records_tenant_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "record_type", name="uq_tenant_records_tenant_id_type"
        ),
    )
    op.create_index(
        "ix_tenant_records_tenant_type_created",
        "tenant_records",
        ["tenant_id", "record_type", "created_at"],
    )
    op.create_index(
        "ix_tenant_records_tenant_org",
        "tenant_records",
        ["tenant_id", "organization_unit_id"],
    )
    op.execute("ALTER TABLE tenant_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_records
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    # Dropping this table deletes tenant records. Roll back only disposable
    # environments or after an explicit backup and dependency check.
    op.execute("DROP POLICY tenant_isolation ON tenant_records")
    op.execute("ALTER TABLE tenant_records NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_records DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_tenant_records_tenant_org", table_name="tenant_records")
    op.drop_index("ix_tenant_records_tenant_type_created", table_name="tenant_records")
    op.drop_table("tenant_records")
