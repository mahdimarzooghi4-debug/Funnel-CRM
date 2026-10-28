"""Record outcomes for campaign signal follow-up work."""

from alembic import op
import sqlalchemy as sa

revision = "20261028_79"
down_revision = "20261028_78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_work_item_campaign_signal_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("metric_key", sa.String(length=80), nullable=False),
        sa.Column("signal_type", sa.String(length=24), nullable=False),
        sa.Column("decision_key", sa.String(length=24), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=False),
        sa.Column("metric_actual", sa.String(length=80), nullable=True),
        sa.Column("metric_target", sa.String(length=80), nullable=False),
        sa.Column("metric_status", sa.String(length=16), nullable=False),
        sa.Column("observed_days", sa.Integer(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_crm_work_item_campaign_signal_outcomes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_work_item_campaign_signal_outcomes_tenant_id"),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_crm_work_item_campaign_signal_outcomes_request"),
        sa.CheckConstraint(
            "decision_key IN ('adjusted', 'data_corrected', 'no_change', 'escalated', 'other')",
            name="ck_crm_work_item_campaign_signal_outcomes_decision",
        ),
        sa.CheckConstraint(
            "signal_type IN ('measurement_gap', 'target_gap')",
            name="ck_crm_work_item_campaign_signal_outcomes_signal_type",
        ),
        sa.CheckConstraint(
            "metric_status IN ('met', 'not_met', 'no_data')",
            name="ck_crm_work_item_campaign_signal_outcomes_metric_status",
        ),
        sa.CheckConstraint(
            "observed_days >= 0 AND period_days > 0 AND observed_days <= period_days",
            name="ck_crm_work_item_campaign_signal_outcomes_coverage",
        ),
        sa.CheckConstraint(
            "length(trim(notes)) BETWEEN 1 AND 2000",
            name="ck_crm_work_item_campaign_signal_outcomes_notes",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_work_item_campaign_signal_outcomes_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "work_item_id"],
            ["crm_work_items.tenant_id", "crm_work_items.id"],
            name="fk_crm_work_item_campaign_signal_outcomes_item_same_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "recorded_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_item_campaign_signal_outcomes_recorder_same_tenant", ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_crm_work_item_campaign_signal_outcomes_tenant_item_time",
        "crm_work_item_campaign_signal_outcomes",
        ["tenant_id", "work_item_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_work_item_campaign_signal_outcomes_tenant_item_time",
        table_name="crm_work_item_campaign_signal_outcomes",
    )
    op.drop_table("crm_work_item_campaign_signal_outcomes")
