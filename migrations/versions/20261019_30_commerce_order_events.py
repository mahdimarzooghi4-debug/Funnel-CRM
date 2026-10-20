"""Store idempotent paid-order and refund facts from connected Funnel products."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_30"
down_revision = "20261019_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_product_commerce_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_product", sa.String(80), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("order_reference", sa.String(200), nullable=False),
        sa.Column("event_kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "source_product", "source_event_id",
            name="uq_crm_product_commerce_events_source_event",
        ),
        sa.CheckConstraint(
            "event_kind IN ('paid', 'refunded')",
            name="ck_crm_product_commerce_events_kind",
        ),
        sa.CheckConstraint(
            "length(trim(order_reference)) BETWEEN 1 AND 200",
            name="ck_crm_product_commerce_events_order_reference",
        ),
        sa.CheckConstraint(
            "amount >= 0 AND currency ~ '^[A-Z]{3}$'",
            name="ck_crm_product_commerce_events_money",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_product_commerce_events_workspace", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_product_commerce_events_org_same_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_product_commerce_events_profile_same_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id",
             "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_product_commerce_events_campaign_same_org",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_crm_product_commerce_events_tenant_org_time",
            "tenant_id", "organization_unit_id", "occurred_at",
        ),
        sa.Index(
            "ix_crm_product_commerce_events_tenant_campaign_time",
            "tenant_id", "campaign_id", "occurred_at",
        ),
    )
    op.execute("ALTER TABLE crm_product_commerce_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_product_commerce_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON crm_product_commerce_events "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    permission_table = sa.table(
        "permission_definitions",
        sa.column("key", sa.String(160)),
        sa.column("description", sa.String(500)),
    )
    op.bulk_insert(permission_table, [{
        "key": "crm.commerce_event:view",
        "description": "View source-recorded commerce outcomes in authorized organization scopes",
    }])


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON crm_product_commerce_events")
    op.execute("ALTER TABLE crm_product_commerce_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_product_commerce_events DISABLE ROW LEVEL SECURITY")
    op.drop_table("crm_product_commerce_events")
    op.execute("DELETE FROM role_permissions WHERE permission_key = 'crm.commerce_event:view'")
    op.execute("DELETE FROM permission_definitions WHERE key = 'crm.commerce_event:view'")
