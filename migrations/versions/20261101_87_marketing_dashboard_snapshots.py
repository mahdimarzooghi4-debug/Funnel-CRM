"""Persist immutable marketing manager dashboard snapshots.

Revision ID: 20261101_87
Revises: 20261031_86
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_87"
down_revision = "20261031_86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_dashboard_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("report_definition_version", sa.String(length=40), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("period_start <= period_end",
                           name="ck_crm_dashboard_snapshots_period"),
        sa.CheckConstraint("length(snapshot_hash) = 64",
                           name="ck_crm_dashboard_snapshots_hash_length"),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], ondelete="CASCADE",
                                name="fk_crm_dashboard_snapshots_workspace"),
        sa.ForeignKeyConstraint(["creator_identity_id"], ["user_identities.id"],
                                ondelete="RESTRICT",
                                name="fk_crm_dashboard_snapshots_creator"),
    )
    op.create_index(
        "ix_crm_dashboard_snapshots_owner_created",
        "crm_marketing_dashboard_snapshots",
        ["tenant_id", "creator_identity_id", "created_at"],
    )
    op.execute("ALTER TABLE crm_marketing_dashboard_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_dashboard_snapshots FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY crm_marketing_dashboard_snapshots_tenant_isolation
        ON crm_marketing_dashboard_snapshots
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE FUNCTION reject_crm_marketing_dashboard_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               OR NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL THEN
                RAISE EXCEPTION 'marketing dashboard snapshots are immutable';
            END IF;
            RETURN OLD;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER crm_marketing_dashboard_snapshots_immutable
        BEFORE UPDATE OR DELETE ON crm_marketing_dashboard_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_crm_marketing_dashboard_snapshot_mutation()
    """)



def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS crm_marketing_dashboard_snapshots_immutable "
               "ON crm_marketing_dashboard_snapshots")
    op.execute("DROP FUNCTION IF EXISTS reject_crm_marketing_dashboard_snapshot_mutation()")
    op.drop_table("crm_marketing_dashboard_snapshots")
