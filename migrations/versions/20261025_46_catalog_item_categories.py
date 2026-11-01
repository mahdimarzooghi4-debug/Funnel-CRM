"""Add searchable catalog categories."""
from alembic import op
import sqlalchemy as sa

revision = "20261025_46"
down_revision = "20261025_45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_product_catalog_items", sa.Column("category", sa.String(120), nullable=True))
    op.create_check_constraint(
        "ck_crm_product_catalog_items_category",
        "crm_product_catalog_items",
        "category IS NULL OR length(trim(category)) BETWEEN 1 AND 120",
    )
    op.create_index(
        "ix_crm_product_catalog_items_tenant_org_category",
        "crm_product_catalog_items",
        ["tenant_id", "organization_unit_id", "category"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_product_catalog_items_tenant_org_category", table_name="crm_product_catalog_items")
    op.drop_constraint("ck_crm_product_catalog_items_category", "crm_product_catalog_items", type_="check")
    op.drop_column("crm_product_catalog_items", "category")
