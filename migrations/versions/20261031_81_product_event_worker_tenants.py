"""Maintain a minimal, non-PII registry for event worker tenant discovery.

Revision ID: 20261031_81
Revises: 20261028_80
"""

from alembic import op
import sqlalchemy as sa

revision = "20261031_81"
down_revision = "20261028_80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_event_worker_tenants",
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_product_event_worker_tenants_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.execute(
        """
        INSERT INTO product_event_worker_tenants (tenant_id)
        SELECT id FROM workspaces
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION register_product_event_worker_tenant()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            INSERT INTO public.product_event_worker_tenants (tenant_id)
            VALUES (NEW.id)
            ON CONFLICT (tenant_id) DO NOTHING;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER workspace_product_event_worker_registration
        AFTER INSERT ON workspaces
        FOR EACH ROW
        EXECUTE FUNCTION register_product_event_worker_tenant()
        """
    )
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON TABLE product_event_worker_tenants FROM PUBLIC"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER workspace_product_event_worker_registration ON workspaces")
    op.execute("DROP FUNCTION register_product_event_worker_tenant()")
    op.drop_table("product_event_worker_tenants")
