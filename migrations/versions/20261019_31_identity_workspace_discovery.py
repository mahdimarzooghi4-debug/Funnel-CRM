"""Add RLS-scoped discovery for an authenticated identity's workspaces.

Revision ID: 20261019_31
Revises: 20261019_30
"""
from alembic import op

revision = "20261019_31"
down_revision = "20261019_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These additive SELECT policies preserve the default tenant_id policy.
    # Workspace membership visibility is constrained to the identity values
    # installed transaction-locally by the trusted authentication layer.
    op.execute("""
        CREATE POLICY identity_membership_discovery
        ON workspace_memberships
        FOR SELECT
        USING (
            status = 'active'
            AND EXISTS (
                SELECT 1
                FROM user_identities AS identity
                WHERE identity.id = workspace_memberships.identity_id
                  AND identity.issuer =
                      NULLIF(current_setting('app.authenticated_issuer', true), '')
                  AND identity.subject =
                      NULLIF(current_setting('app.authenticated_subject', true), '')
            )
        )
    """)
    op.execute("""
        CREATE POLICY identity_workspace_discovery
        ON workspaces
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM workspace_memberships AS membership
                WHERE membership.tenant_id = workspaces.id
                  AND membership.status = 'active'
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY identity_workspace_discovery ON workspaces")
    op.execute(
        "DROP POLICY identity_membership_discovery ON workspace_memberships"
    )
