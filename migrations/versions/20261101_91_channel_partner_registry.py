"""Create tenant and organization scoped sales channel partner records.

Revision ID: 20261101_91
Revises: 20261101_90
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_91"
down_revision = "20261101_90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("INSERT INTO permission_definitions (key, description) VALUES ('crm.partner:view', 'View CRM channel partners'), ('crm.partner:manage', 'Manage CRM channel partners') ON CONFLICT (key) DO NOTHING")
    op.create_table(
        "crm_channel_partners",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("partner_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="prospect"),
        sa.Column("contact_name", sa.String(160)),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(40)),
        sa.Column("territory", sa.String(160)),
        sa.Column("notes", sa.String(2000)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_channel_partners_tenant_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 180", name="ck_crm_channel_partners_name"),
        sa.CheckConstraint("partner_type IN ('reseller','affiliate','agency','distributor','referral','other')", name="ck_crm_channel_partners_type"),
        sa.CheckConstraint("status IN ('prospect','active','paused','ended')", name="ck_crm_channel_partners_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], ondelete="CASCADE", name="fk_crm_channel_partners_workspace"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"], ["organization_units.tenant_id", "organization_units.id"], ondelete="RESTRICT", name="fk_crm_channel_partners_org_same_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["workspace_memberships.tenant_id", "workspace_memberships.id"], ondelete="CASCADE", name="fk_crm_channel_partners_creator_same_tenant"),
    )
    op.create_index("ix_crm_channel_partners_tenant_org_status", "crm_channel_partners", ["tenant_id", "organization_unit_id", "status"])
    op.execute("ALTER TABLE crm_channel_partners ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_channel_partners FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY crm_channel_partners_tenant_isolation ON crm_channel_partners USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def downgrade() -> None:
    op.drop_table("crm_channel_partners")
    op.execute("DELETE FROM role_permissions WHERE permission_key IN ('crm.partner:view','crm.partner:manage')")
    op.execute("DELETE FROM permission_definitions WHERE key IN ('crm.partner:view','crm.partner:manage')")
