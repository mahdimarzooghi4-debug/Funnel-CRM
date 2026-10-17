"""Add append-only audit events for authorization and organization changes.

Revision ID: 20261017_05
Revises: 20261017_04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261017_05"
down_revision = "20261017_04"
branch_labels = None
depends_on = None


AUDITED_TABLES = (
    "organization_units",
    "workspace_memberships",
    "roles",
    "role_permissions",
    "role_assignments",
)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_identity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_key", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_key", sa.String(length=250), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'system')",
            name="ck_audit_events_actor_kind",
        ),
        sa.CheckConstraint(
            "(actor_kind = 'user' AND actor_identity_id IS NOT NULL "
            "AND actor_membership_id IS NOT NULL) OR "
            "(actor_kind = 'system' AND actor_identity_id IS NULL "
            "AND actor_membership_id IS NULL)",
            name="ck_audit_events_actor_shape",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_audit_events_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("tenant_id", "event_id", name="uq_audit_events_tenant_event"),
    )
    op.create_index(
        "ix_audit_events_tenant_time", "audit_events", ["tenant_id", "occurred_at"]
    )
    op.create_index(
        "ix_audit_events_tenant_actor_time",
        "audit_events",
        ["tenant_id", "actor_identity_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_events_tenant_target_time",
        "audit_events",
        ["tenant_id", "target_type", "target_key", "occurred_at"],
    )

    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_events
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        """
    )

    op.execute(
        """
        CREATE FUNCTION protect_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- A tenant purge is the only cascade that may remove audit rows.
            -- Direct UPDATE/DELETE by application or table owners remains blocked.
            IF pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION protect_audit_event_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION capture_security_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            row_data jsonb;
            old_data jsonb;
            new_data jsonb;
            tenant_value uuid;
            actor_identity_value uuid;
            actor_membership_value uuid;
            actor_type_value text;
            event_target_type text;
            event_target_key text;
            event_org_unit uuid;
            event_action text;
        BEGIN
            -- Tenant deletion cascades already remove the audit rows. Do not
            -- create new audit rows after the parent workspace has been removed.
            IF TG_OP = 'INSERT' THEN
                row_data := to_jsonb(NEW);
                new_data := row_data;
                old_data := NULL;
            ELSIF TG_OP = 'DELETE' THEN
                row_data := to_jsonb(OLD);
                new_data := NULL;
                old_data := row_data;
            ELSE
                row_data := to_jsonb(NEW);
                new_data := row_data;
                old_data := to_jsonb(OLD);
            END IF;

            tenant_value := (row_data ->> 'tenant_id')::uuid;
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM workspaces WHERE id = tenant_value
            ) THEN
                RETURN OLD;
            END IF;

            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;

            IF NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL THEN
                IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                    RAISE EXCEPTION 'verified actor context is required for tenant changes'
                        USING ERRCODE = '42501';
                END IF;
                actor_type_value := 'user';
            ELSE
                actor_identity_value := NULL;
                actor_membership_value := NULL;
                actor_type_value := 'system';
            END IF;

            event_target_type := CASE TG_TABLE_NAME
                WHEN 'organization_units' THEN 'organization_unit'
                WHEN 'workspace_memberships' THEN 'workspace_membership'
                WHEN 'role_permissions' THEN 'role_permission'
                WHEN 'role_assignments' THEN 'role_assignment'
                ELSE 'role'
            END;
            event_target_key := CASE
                WHEN TG_TABLE_NAME = 'role_permissions' THEN
                    (row_data ->> 'role_id') || ':' || (row_data ->> 'permission_key')
                ELSE row_data ->> 'id'
            END;
            event_org_unit := CASE
                WHEN TG_TABLE_NAME = 'organization_units' THEN
                    (row_data ->> 'id')::uuid
                WHEN TG_TABLE_NAME = 'role_assignments' THEN
                    (row_data ->> 'organization_unit_id')::uuid
                ELSE NULL
            END;
            event_action := event_target_type || '.' || CASE TG_OP
                WHEN 'INSERT' THEN 'created'
                WHEN 'UPDATE' THEN 'updated'
                ELSE 'deleted'
            END;

            INSERT INTO audit_events (
                tenant_id,
                actor_kind,
                actor_identity_id,
                actor_membership_id,
                action_key,
                target_type,
                target_key,
                organization_unit_id,
                before_state,
                after_state,
                correlation_id
            ) VALUES (
                tenant_value,
                actor_type_value,
                actor_identity_value,
                actor_membership_value,
                event_action,
                event_target_type,
                event_target_key,
                event_org_unit,
                old_data,
                new_data,
                NULLIF(current_setting('app.correlation_id', true), '')::uuid
            );

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in AUDITED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER security_audit_{table}
            AFTER INSERT OR UPDATE OR DELETE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION capture_security_audit_event()
            """
        )


def downgrade() -> None:
    for table in reversed(AUDITED_TABLES):
        op.execute(f'DROP TRIGGER security_audit_{table} ON "{table}"')
    op.execute("DROP FUNCTION capture_security_audit_event()")
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION protect_audit_event_mutation()")
    op.execute("DROP POLICY tenant_isolation ON audit_events")
    op.execute("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_audit_events_tenant_target_time", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_actor_time", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_time", table_name="audit_events")
    op.drop_table("audit_events")
