"""Persist observed follow-up measurements for manager actions.

Revision ID: 20261101_90
Revises: 20261101_89
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_90"
down_revision = "20261101_89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_crm_dashboard_actions_tenant_id",
        "crm_marketing_dashboard_actions",
        ["tenant_id", "id"],
    )
    op.create_table(
        "crm_marketing_dashboard_action_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baseline_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_path", sa.String(length=500), nullable=False),
        sa.Column("baseline_value", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("current_value", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("absolute_change", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("expected_direction", sa.String(length=16), nullable=True),
        sa.Column("direction_matched", sa.Boolean(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "expected_direction IS NULL OR expected_direction IN "
            "('increase', 'decrease', 'unchanged')",
            name="ck_crm_dashboard_action_verification_direction",
        ),
        sa.CheckConstraint(
            "(expected_direction IS NULL AND direction_matched IS NULL) OR "
            "(expected_direction IS NOT NULL AND direction_matched IS NOT NULL)",
            name="ck_crm_dashboard_action_verification_match_shape",
        ),
        sa.CheckConstraint(
            "baseline_snapshot_id <> current_snapshot_id",
            name="ck_crm_dashboard_action_verification_distinct_snapshots",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"], ondelete="CASCADE",
                                name="fk_crm_dashboard_action_verifications_workspace"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "action_id"],
            ["crm_marketing_dashboard_actions.tenant_id",
             "crm_marketing_dashboard_actions.id"],
            ondelete="CASCADE",
            name="fk_crm_dashboard_action_verifications_action_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "baseline_snapshot_id"],
            ["crm_marketing_dashboard_snapshots.tenant_id",
             "crm_marketing_dashboard_snapshots.id"],
            ondelete="CASCADE",
            name="fk_crm_dashboard_action_verifications_baseline_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "current_snapshot_id"],
            ["crm_marketing_dashboard_snapshots.tenant_id",
             "crm_marketing_dashboard_snapshots.id"],
            ondelete="CASCADE",
            name="fk_crm_dashboard_action_verifications_current_same_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "action_id", "current_snapshot_id", "metric_path",
            name="uq_crm_dashboard_action_verification_snapshot_metric",
        ),
    )
    op.create_index(
        "ix_crm_dashboard_action_verifications_action_time",
        "crm_marketing_dashboard_action_verifications",
        ["tenant_id", "action_id", "verified_at"],
    )
    op.execute(
        "ALTER TABLE crm_marketing_dashboard_action_verifications ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE crm_marketing_dashboard_action_verifications FORCE ROW LEVEL SECURITY"
    )
    op.execute("""
        CREATE POLICY crm_marketing_dashboard_action_verifications_tenant_isolation
        ON crm_marketing_dashboard_action_verifications
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE FUNCTION protect_crm_marketing_dashboard_action_verification()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               OR (
                   TG_OP = 'DELETE'
                   AND pg_trigger_depth() <= 1
                   AND NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
               ) THEN
                RAISE EXCEPTION 'dashboard action verifications are immutable';
            END IF;
            RETURN OLD;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER crm_marketing_dashboard_action_verifications_immutable
        BEFORE UPDATE OR DELETE ON crm_marketing_dashboard_action_verifications
        FOR EACH ROW EXECUTE FUNCTION protect_crm_marketing_dashboard_action_verification()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS crm_marketing_dashboard_action_verifications_immutable "
        "ON crm_marketing_dashboard_action_verifications"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS protect_crm_marketing_dashboard_action_verification()"
    )
    op.drop_table("crm_marketing_dashboard_action_verifications")
    op.drop_constraint(
        "uq_crm_dashboard_actions_tenant_id",
        "crm_marketing_dashboard_actions",
        type_="unique",
    )
