"""Add manager-owned marketing learning cycles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_28"
down_revision = "20261018_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_marketing_learning_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("follow_up_target_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assessment", sa.String(1200), nullable=False),
        sa.Column("corrective_action", sa.String(1200), nullable=False),
        sa.Column("follow_up_effectiveness", sa.String(1200), nullable=True),
        sa.Column("lesson_learned", sa.String(1200), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_learning_reviews_tenant_id"),
        sa.CheckConstraint(
            "length(trim(assessment)) BETWEEN 1 AND 1200 "
            "AND length(trim(corrective_action)) BETWEEN 1 AND 1200",
            name="ck_crm_marketing_learning_reviews_required_text",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'evaluated')",
            name="ck_crm_marketing_learning_reviews_status",
        ),
        sa.CheckConstraint(
            "(status = 'planned' AND follow_up_target_plan_id IS NULL "
            "AND follow_up_effectiveness IS NULL AND lesson_learned IS NULL) OR "
            "(status = 'evaluated' AND follow_up_target_plan_id IS NOT NULL "
            "AND follow_up_effectiveness IS NOT NULL AND length(trim(follow_up_effectiveness)) > 0 "
            "AND lesson_learned IS NOT NULL AND length(trim(lesson_learned)) > 0)",
            name="ck_crm_marketing_learning_reviews_evaluation",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_learning_reviews_workspace", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_learning_reviews_org_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_learning_reviews_campaign_same_org", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "target_plan_id"],
            ["crm_marketing_campaign_target_plans.tenant_id",
             "crm_marketing_campaign_target_plans.id"],
            name="fk_crm_marketing_learning_reviews_target_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "follow_up_target_plan_id"],
            ["crm_marketing_campaign_target_plans.tenant_id",
             "crm_marketing_campaign_target_plans.id"],
            name="fk_crm_marketing_learning_reviews_followup_same_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "experiment_id"],
            ["crm_marketing_campaign_experiments.tenant_id",
             "crm_marketing_campaign_experiments.organization_unit_id",
             "crm_marketing_campaign_experiments.id"],
            name="fk_crm_marketing_learning_reviews_experiment_same_org", ondelete="RESTRICT"),
        sa.Index("ix_crm_marketing_learning_reviews_tenant_campaign_status",
                 "tenant_id", "campaign_id", "status"),
    )
    op.execute("ALTER TABLE crm_marketing_learning_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_learning_reviews FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_marketing_learning_reviews "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_marketing_learning_reviews")
    op.execute("ALTER TABLE crm_marketing_learning_reviews NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_marketing_learning_reviews DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_marketing_learning_reviews")
