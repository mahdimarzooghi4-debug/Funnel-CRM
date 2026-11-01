"""Persist campaign target signal source on work items."""

from alembic import op
import sqlalchemy as sa

revision = "20261028_78"
down_revision = "20261028_77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_work_items", sa.Column("source_campaign_target_plan_id", sa.Uuid(), nullable=True))
    op.add_column("crm_work_items", sa.Column("source_campaign_metric_key", sa.String(length=80), nullable=True))
    op.add_column("crm_work_items", sa.Column("source_campaign_signal_type", sa.String(length=24), nullable=True))
    op.create_check_constraint(
        "ck_crm_work_items_campaign_signal_source",
        "crm_work_items",
        "(source_campaign_target_plan_id IS NULL AND source_campaign_metric_key IS NULL AND source_campaign_signal_type IS NULL) OR "
        "(source_campaign_target_plan_id IS NOT NULL AND campaign_id IS NOT NULL "
        "AND source_campaign_metric_key IS NOT NULL AND source_campaign_signal_type IN ('measurement_gap', 'target_gap'))",
    )
    op.create_foreign_key(
        "fk_crm_work_items_campaign_target_plan_same_tenant",
        "crm_work_items",
        "crm_marketing_campaign_target_plans",
        ["tenant_id", "source_campaign_target_plan_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_crm_work_items_open_campaign_signal",
        "crm_work_items",
        ["tenant_id", "campaign_id", "source_campaign_target_plan_id", "source_campaign_metric_key"],
        unique=True,
        postgresql_where=sa.text(
            "source_campaign_target_plan_id IS NOT NULL AND status IN ('open', 'in_progress')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_crm_work_items_open_campaign_signal", table_name="crm_work_items")
    op.drop_constraint(
        "fk_crm_work_items_campaign_target_plan_same_tenant",
        "crm_work_items",
        type_="foreignkey",
    )
    op.drop_constraint("ck_crm_work_items_campaign_signal_source", "crm_work_items", type_="check")
    op.drop_column("crm_work_items", "source_campaign_signal_type")
    op.drop_column("crm_work_items", "source_campaign_metric_key")
    op.drop_column("crm_work_items", "source_campaign_target_plan_id")
