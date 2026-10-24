"""Add keyed contact-point indexes for private duplicate detection.

Revision ID: 20261018_05
Revises: 20261018_04
"""

from alembic import op
import sqlalchemy as sa

revision = "20261018_05"
down_revision = "20261018_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_contact_points",
        sa.Column("fingerprint_key_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "crm_contact_points",
        sa.Column("match_fingerprint", sa.LargeBinary(), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_contact_points_fingerprint_pair",
        "crm_contact_points",
        "(match_fingerprint IS NULL AND fingerprint_key_id IS NULL) OR "
        "(octet_length(match_fingerprint) = 32 AND "
        "length(trim(fingerprint_key_id)) BETWEEN 1 AND 64)",
    )
    op.create_index(
        "ix_crm_contact_points_blind_match",
        "crm_contact_points",
        ["tenant_id", "channel", "fingerprint_key_id", "match_fingerprint"],
    )
    op.execute(
        """
        INSERT INTO permission_definitions (key, description) VALUES
            ('crm.profile:review_duplicates', 'Review private duplicate profile candidates')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_key = 'crm.profile:review_duplicates'
        """
    )
    op.execute(
        """
        DELETE FROM permission_definitions
        WHERE key = 'crm.profile:review_duplicates'
        """
    )
    op.drop_index(
        "ix_crm_contact_points_blind_match",
        table_name="crm_contact_points",
    )
    op.drop_constraint(
        "ck_crm_contact_points_fingerprint_pair",
        "crm_contact_points",
        type_="check",
    )
    op.drop_column("crm_contact_points", "match_fingerprint")
    op.drop_column("crm_contact_points", "fingerprint_key_id")
