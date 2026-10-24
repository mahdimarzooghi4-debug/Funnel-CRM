"""Enable and force row-level tenant isolation.

Revision ID: 20261017_03
Revises: 20261016_02
"""

from alembic import op

revision = "20261017_03"
down_revision = "20261016_02"
branch_labels = None
depends_on = None

TENANT_TABLES = {
    "workspaces": "id",
    "organization_units": "tenant_id",
    "workspace_memberships": "tenant_id",
    "roles": "tenant_id",
    "role_permissions": "tenant_id",
    "role_assignments": "tenant_id",
}


def upgrade() -> None:
    for table, tenant_column in TENANT_TABLES.items():
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON "{table}"
            USING (
                "{tenant_column}" =
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                "{tenant_column}" =
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            """
        )


def downgrade() -> None:
    for table in reversed(tuple(TENANT_TABLES)):
        op.execute(f'DROP POLICY tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
