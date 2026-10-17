"""Add saved, scoped CRM profile segments.

Revision ID: 20261018_09
Revises: 20261018_08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_09"
down_revision = "20261018_08"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("crm.segment:view", "View CRM audience segments"),
    ("crm.segment:manage", "Create and manage CRM audience segments"),
)


def upgrade() -> None:
    permission_values = ",\n".join(
        f"('{key}', '{description}')" for key, description in PERMISSIONS
    )
    op.execute(
        f"""
        INSERT INTO permission_definitions (key, description)
        VALUES {permission_values}
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.create_table(
        "crm_profile_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_crm_profile_segments_name",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(criteria) = 'object' AND octet_length(criteria::text) <= 4096",
            name="ck_crm_profile_segments_criteria",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_profile_segments_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_profile_segments_org_same_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_crm_profile_segments_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "organization_unit_id",
            "name",
            name="uq_crm_profile_segments_tenant_org_name",
        ),
    )
    op.create_index(
        "ix_crm_profile_segments_tenant_org_active",
        "crm_profile_segments",
        ["tenant_id", "organization_unit_id", "is_active"],
    )
    op.execute("ALTER TABLE crm_profile_segments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_profile_segments FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_profile_segments
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_profile_segments")
    op.execute("ALTER TABLE crm_profile_segments NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_profile_segments DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_profile_segments_tenant_org_active", table_name="crm_profile_segments")
    op.drop_table("crm_profile_segments")
    keys = ", ".join(f"'{key}'" for key, _description in PERMISSIONS)
    op.execute(f"DELETE FROM role_permissions WHERE permission_key IN ({keys})")
    op.execute(f"DELETE FROM permission_definitions WHERE key IN ({keys})")
