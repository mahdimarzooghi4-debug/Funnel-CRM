"""Store communication purpose on each marketing campaign."""

from alembic import op
import sqlalchemy as sa

revision = "20261028_80"
down_revision = "20261028_79"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_marketing_campaigns",
        sa.Column(
            "communication_purpose_key",
            sa.String(length=80),
            nullable=False,
            server_default="marketing",
        ),
    )
    op.create_check_constraint(
        "ck_crm_marketing_campaigns_communication_purpose",
        "crm_marketing_campaigns",
        "communication_purpose_key ~ '^[a-z][a-z0-9_.-]{0,79}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_marketing_campaigns_communication_purpose",
        "crm_marketing_campaigns",
        type_="check",
    )
    op.drop_column("crm_marketing_campaigns", "communication_purpose_key")
