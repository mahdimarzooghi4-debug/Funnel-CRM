"""Add immutable purpose/channel-scoped communication consent events.

Revision ID: 20261018_04
Revises: 20261018_03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_04"
down_revision = "20261018_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_communication_consent_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose_key", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose_key ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_consent_purpose_key",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'phone', 'postal_address', 'social_handle', 'website')",
            name="ck_crm_consent_channel",
        ),
        sa.CheckConstraint(
            "decision IN ('granted', 'withdrawn')",
            name="ck_crm_consent_decision",
        ),
        sa.CheckConstraint(
            "length(trim(policy_version)) BETWEEN 1 AND 64",
            name="ck_crm_consent_policy_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_consent_profile_same_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_crm_consent_latest_by_scope",
        "crm_communication_consent_events",
        ["tenant_id", "profile_id", "purpose_key", "channel", "recorded_at", "id"],
    )
    op.execute(
        "ALTER TABLE crm_communication_consent_events ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE crm_communication_consent_events FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_communication_consent_events
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        INSERT INTO permission_definitions (key, description) VALUES
            ('crm.communication_consent:view', 'View communication consent history and eligibility'),
            ('crm.communication_consent:record', 'Record an explicit communication decision')
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_crm_communication_consent_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- Referential cascades support profile and workspace erasure.
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'communication consent events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_communication_consent_append_only
        BEFORE UPDATE OR DELETE ON crm_communication_consent_events
        FOR EACH ROW EXECUTE FUNCTION protect_crm_communication_consent_event()
        """
    )
    op.execute(
        """
        CREATE FUNCTION capture_crm_communication_consent_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            actor_identity_value uuid;
            actor_membership_value uuid;
            event_org_unit uuid;
        BEGIN
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NULL
               OR NULLIF(current_setting('app.tenant_id', true), '')::uuid <> NEW.tenant_id THEN
                RAISE EXCEPTION 'verified tenant context is required for consent events'
                    USING ERRCODE = '42501';
            END IF;
            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
            IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                RAISE EXCEPTION 'verified actor context is required for consent events'
                    USING ERRCODE = '42501';
            END IF;

            SELECT organization_unit_id INTO event_org_unit
            FROM crm_profiles
            WHERE tenant_id = NEW.tenant_id AND id = NEW.profile_id;

            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                NEW.tenant_id, 'user', actor_identity_value, actor_membership_value,
                'crm.communication_consent.' || NEW.decision,
                'crm_communication_consent_event', NEW.id::text, event_org_unit,
                NULL,
                jsonb_build_object(
                    'purpose_key', NEW.purpose_key,
                    'channel', NEW.channel,
                    'decision', NEW.decision,
                    'policy_version', NEW.policy_version
                ),
                NULLIF(current_setting('app.correlation_id', true), '')::uuid
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_audit_communication_consent_insert
        AFTER INSERT ON crm_communication_consent_events
        FOR EACH ROW EXECUTE FUNCTION capture_crm_communication_consent_audit_event()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER crm_audit_communication_consent_insert ON crm_communication_consent_events"
    )
    op.execute("DROP FUNCTION capture_crm_communication_consent_audit_event()")
    op.execute(
        "DROP TRIGGER crm_communication_consent_append_only ON crm_communication_consent_events"
    )
    op.execute("DROP FUNCTION protect_crm_communication_consent_event()")
    op.execute(
        "DROP POLICY tenant_isolation ON crm_communication_consent_events"
    )
    op.execute(
        "ALTER TABLE crm_communication_consent_events NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE crm_communication_consent_events DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_crm_consent_latest_by_scope",
        table_name="crm_communication_consent_events",
    )
    op.drop_table("crm_communication_consent_events")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_key IN (
            'crm.communication_consent:view',
            'crm.communication_consent:record'
        )
        """
    )
    op.execute(
        """
        DELETE FROM permission_definitions
        WHERE key IN (
            'crm.communication_consent:view',
            'crm.communication_consent:record'
        )
        """
    )
