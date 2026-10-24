"""Add support case conversations and first-response tracking."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261024_33"
down_revision = "20261024_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_support_cases",
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "crm_support_case_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("support_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_kind", sa.String(24), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_support_case_entries_tenant_id"),
        sa.CheckConstraint(
            "entry_kind IN ('internal_note', 'response_record')",
            name="ck_crm_support_case_entries_kind"),
        sa.CheckConstraint("length(trim(body)) BETWEEN 1 AND 4000",
                           name="ck_crm_support_case_entries_body"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_support_case_entries_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "support_case_id"],
            ["crm_support_cases.tenant_id", "crm_support_cases.id"],
            name="fk_crm_support_case_entries_case_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "author_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_support_case_entries_author_same_tenant", ondelete="RESTRICT"),
        sa.Index("ix_crm_support_case_entries_tenant_case_created",
                 "tenant_id", "support_case_id", "created_at", "id"),
    )
    op.execute("ALTER TABLE crm_support_case_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_support_case_entries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_support_case_entries "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_support_case_entries")
    op.execute("ALTER TABLE crm_support_case_entries NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_support_case_entries DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_support_case_entries")
    op.drop_column("crm_support_cases", "first_response_at")
