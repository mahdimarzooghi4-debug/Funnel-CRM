"""Store tenant-scoped, product-originated CRM customer activities.

Revision ID: 20261018_18
Revises: 20261018_17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_18"
down_revision = "20261018_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_customer_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_product", sa.String(length=80), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("source_record_id", sa.String(length=200), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_crm_customer_activities_source",
        ),
        sa.CheckConstraint(
            "activity_type ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_customer_activities_type",
        ),
        sa.CheckConstraint(
            "channel IN ('online', 'phone', 'store', 'field', 'support', 'campaign', 'other')",
            name="ck_crm_customer_activities_channel",
        ),
        sa.CheckConstraint(
            "source_record_id IS NULL OR length(trim(source_record_id)) BETWEEN 1 AND 200",
            name="ck_crm_customer_activities_source_record",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_customer_activities_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_customer_activities_profile_same_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_product",
            "source_event_id",
            name="uq_crm_customer_activities_source_event",
        ),
    )
    op.create_index(
        "ix_crm_customer_activities_tenant_profile_time",
        "crm_customer_activities",
        ["tenant_id", "profile_id", "occurred_at"],
    )
    op.execute("ALTER TABLE crm_customer_activities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_customer_activities FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_customer_activities
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE FUNCTION deny_crm_customer_activity_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            -- Permit cleanup only when an FK cascade removes a parent profile or tenant.
            IF pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'CRM customer activities are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_customer_activities_append_only
        BEFORE UPDATE OR DELETE ON crm_customer_activities
        FOR EACH ROW EXECUTE FUNCTION deny_crm_customer_activity_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER crm_customer_activities_append_only ON crm_customer_activities"
    )
    op.execute("DROP FUNCTION deny_crm_customer_activity_mutation()")
    op.execute("DROP POLICY tenant_isolation ON crm_customer_activities")
    op.execute(
        "ALTER TABLE crm_customer_activities NO FORCE ROW LEVEL SECURITY"
    )
    op.execute("ALTER TABLE crm_customer_activities DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_crm_customer_activities_tenant_profile_time",
        table_name="crm_customer_activities",
    )
    op.drop_table("crm_customer_activities")
