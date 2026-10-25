"""Record human follow-up attempt outcomes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261025_36"
down_revision = "20261024_35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_work_item_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_code", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_work_item_outcomes_tenant_id"),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_crm_work_item_outcomes_request"),
        sa.CheckConstraint(
            "outcome_code IN ('contact_made', 'no_contact', 'callback_requested', 'not_interested', 'other')",
            name="ck_crm_work_item_outcomes_code",
        ),
        sa.CheckConstraint(
            "channel IN ('online', 'phone', 'store', 'field', 'support', 'campaign', 'other')",
            name="ck_crm_work_item_outcomes_channel",
        ),
        sa.CheckConstraint("notes IS NULL OR length(notes) <= 2000",
                           name="ck_crm_work_item_outcomes_notes_length"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_work_item_outcomes_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_work_item_outcomes_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "work_item_id"],
            ["crm_work_items.tenant_id", "crm_work_items.id"],
            name="fk_crm_work_item_outcomes_item_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_work_item_outcomes_profile_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "recorded_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_item_outcomes_recorder_same_tenant", ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_crm_work_item_outcomes_tenant_org_time",
        "crm_work_item_outcomes", ["tenant_id", "organization_unit_id", "occurred_at"],
    )
    op.create_index(
        "ix_crm_work_item_outcomes_tenant_item_time",
        "crm_work_item_outcomes", ["tenant_id", "work_item_id", "occurred_at"],
    )
    permission_table = sa.table(
        "permission_definitions",
        sa.column("key", sa.String(160)),
        sa.column("description", sa.String(500)),
    )
    op.bulk_insert(permission_table, [{
        "key": "crm.work_item:record_outcome",
        "description": "Record outcomes for lifecycle follow-up work items in authorized organization scopes",
    }])
    op.execute("ALTER TABLE crm_work_item_outcomes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_work_item_outcomes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_work_item_outcomes "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_work_item_outcomes")
    op.execute("ALTER TABLE crm_work_item_outcomes NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_work_item_outcomes DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crm_work_item_outcomes_tenant_item_time", table_name="crm_work_item_outcomes")
    op.drop_index("ix_crm_work_item_outcomes_tenant_org_time", table_name="crm_work_item_outcomes")
    op.drop_table("crm_work_item_outcomes")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key = 'crm.work_item:record_outcome'"
    )
    op.execute(
        "DELETE FROM permission_definitions WHERE key = 'crm.work_item:record_outcome'"
    )
