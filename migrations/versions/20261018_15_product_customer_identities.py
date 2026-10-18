"""Map product customer IDs to tenant-owned CRM profiles.

Revision ID: 20261018_15
Revises: 20261018_14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_15"
down_revision = "20261018_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_customer_identities",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_product", sa.String(length=80), nullable=False),
        sa.Column("external_customer_id", sa.String(length=200), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_product_customer_identities_source",
        ),
        sa.CheckConstraint(
            "length(trim(external_customer_id)) BETWEEN 1 AND 200",
            name="ck_product_customer_identities_external_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_product_customer_identities_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_product_customer_identities_profile_same_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "source_product", "external_customer_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_product",
            "profile_id",
            name="uq_product_customer_identities_profile_source",
        ),
    )
    op.create_index(
        "ix_product_customer_identities_tenant_profile",
        "product_customer_identities",
        ["tenant_id", "profile_id"],
    )
    op.execute("ALTER TABLE product_customer_identities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_customer_identities FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON product_customer_identities
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON product_customer_identities")
    op.execute("ALTER TABLE product_customer_identities NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_customer_identities DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_product_customer_identities_tenant_profile",
        table_name="product_customer_identities",
    )
    op.drop_table("product_customer_identities")
