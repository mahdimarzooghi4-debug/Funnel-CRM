"""Add manager action tracking to dashboard snapshots.

Revision ID: 20261101_88
Revises: 20261101_87
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_88"
down_revision = "20261101_87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_crm_dashboard_snapshots_tenant_id",
        "crm_marketing_dashboard_snapshots",
        ["tenant_id", "id"],
    )
    op.create_table(
        "crm_marketing_dashboard_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="open"),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('open', 'completed', 'cancelled')",
            name="ck_crm_dashboard_actions_status",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND outcome IS NULL) OR "
            "(status IN ('completed', 'cancelled') AND outcome IS NOT NULL "
            "AND length(btrim(outcome)) > 0)",
            name="ck_crm_dashboard_actions_outcome",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], ondelete="CASCADE",
                                name="fk_crm_dashboard_actions_workspace"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["crm_marketing_dashboard_snapshots.tenant_id",
             "crm_marketing_dashboard_snapshots.id"],
            ondelete="CASCADE",
            name="fk_crm_dashboard_actions_snapshot_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["creator_identity_id"], ["user_identities.id"],
            ondelete="RESTRICT",
            name="fk_crm_dashboard_actions_creator",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assigned_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            ondelete="RESTRICT",
            name="fk_crm_dashboard_actions_assignee_same_tenant",
        ),
    )
    op.create_index(
        "ix_crm_dashboard_actions_snapshot_created",
        "crm_marketing_dashboard_actions",
        ["tenant_id", "snapshot_id", "created_at"],
    )
    op.execute("ALTER TABLE crm_marketing_dashboard_actions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_dashboard_actions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY crm_marketing_dashboard_actions_tenant_isolation
        ON crm_marketing_dashboard_actions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE FUNCTION protect_crm_marketing_dashboard_action_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL THEN
                    RAISE EXCEPTION 'marketing dashboard actions cannot be deleted';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status <> 'open'
               OR NEW.status NOT IN ('completed', 'cancelled')
               OR NEW.id IS DISTINCT FROM OLD.id
               OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
               OR NEW.creator_identity_id IS DISTINCT FROM OLD.creator_identity_id
               OR NEW.assigned_membership_id IS DISTINCT FROM OLD.assigned_membership_id
               OR NEW.title IS DISTINCT FROM OLD.title
               OR NEW.decision_note IS DISTINCT FROM OLD.decision_note
               OR NEW.due_on IS DISTINCT FROM OLD.due_on
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.outcome IS NULL
               OR length(btrim(NEW.outcome)) = 0 THEN
                RAISE EXCEPTION 'invalid marketing dashboard action transition';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER crm_marketing_dashboard_actions_transition
        BEFORE UPDATE OR DELETE ON crm_marketing_dashboard_actions
        FOR EACH ROW EXECUTE FUNCTION protect_crm_marketing_dashboard_action_transition()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS crm_marketing_dashboard_actions_transition "
               "ON crm_marketing_dashboard_actions")
    op.execute("DROP FUNCTION IF EXISTS protect_crm_marketing_dashboard_action_transition()")
    op.drop_table("crm_marketing_dashboard_actions")
    op.drop_constraint(
        "uq_crm_dashboard_snapshots_tenant_id",
        "crm_marketing_dashboard_snapshots",
        type_="unique",
    )
