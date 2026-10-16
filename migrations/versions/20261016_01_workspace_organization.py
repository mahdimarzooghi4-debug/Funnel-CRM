"""Create tenant workspaces and organization roots.

Revision ID: 20261016_01
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261016_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("root_organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "root_organization_type",
            sa.String(length=32),
            server_default="root",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "root_organization_type = 'root'",
            name="ck_workspaces_root_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organization_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "unit_type IN ('root', 'unit')",
            name="ck_organization_units_unit_type",
        ),
        sa.CheckConstraint(
            "(unit_type = 'root' AND parent_id IS NULL) OR "
            "(unit_type = 'unit' AND parent_id IS NOT NULL)",
            name="ck_organization_units_root_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_organization_units_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_organization_units_parent_same_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_organization_units_tenant_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "unit_type",
            name="uq_organization_units_tenant_id_type",
        ),
    )
    op.create_index(
        "uq_organization_units_one_root_per_tenant",
        "organization_units",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("unit_type = 'root'"),
    )
    op.create_foreign_key(
        "fk_workspaces_root_organization_same_tenant",
        "workspaces",
        "organization_units",
        ["id", "root_organization_id", "root_organization_type"],
        ["tenant_id", "id", "unit_type"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_workspaces_root_organization_same_tenant",
        "workspaces",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_organization_units_one_root_per_tenant",
        table_name="organization_units",
    )
    op.drop_table("organization_units")
    op.drop_table("workspaces")
