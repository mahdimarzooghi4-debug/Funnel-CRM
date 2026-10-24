"""Allow verified product connections to create encrypted CRM contacts.

Revision ID: 20261018_17
Revises: 20261018_16
"""
from alembic import op

revision = "20261018_17"
down_revision = "20261018_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION capture_crm_contact_point_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_row jsonb;
            old_row jsonb;
            new_row jsonb;
            old_snapshot jsonb;
            new_snapshot jsonb;
            tenant_value uuid;
            profile_value uuid;
            actor_identity_value uuid;
            actor_membership_value uuid;
            integration_connection_value uuid;
            actor_type_value text;
            event_org_unit uuid;
            event_action text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                current_row := to_jsonb(NEW);
                new_row := current_row;
                old_row := NULL;
            ELSIF TG_OP = 'DELETE' THEN
                current_row := to_jsonb(OLD);
                new_row := NULL;
                old_row := current_row;
            ELSE
                current_row := to_jsonb(NEW);
                new_row := current_row;
                old_row := to_jsonb(OLD);
            END IF;

            tenant_value := (current_row ->> 'tenant_id')::uuid;
            profile_value := (current_row ->> 'profile_id')::uuid;
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL THEN
                IF NULLIF(current_setting('app.tenant_id', true), '')::uuid <> tenant_value THEN
                    RAISE EXCEPTION 'contact point tenant does not match verified context'
                        USING ERRCODE = '42501';
                END IF;
                actor_identity_value :=
                    NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
                actor_membership_value :=
                    NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
                integration_connection_value :=
                    NULLIF(current_setting('app.integration_connection_id', true), '')::uuid;
                IF actor_identity_value IS NOT NULL AND actor_membership_value IS NOT NULL
                   AND integration_connection_value IS NULL THEN
                    actor_type_value := 'user';
                ELSIF actor_identity_value IS NULL AND actor_membership_value IS NULL
                   AND integration_connection_value IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM product_connections
                       WHERE tenant_id = tenant_value
                         AND id = integration_connection_value
                   ) THEN
                    actor_identity_value := NULL;
                    actor_membership_value := NULL;
                    actor_type_value := 'system';
                ELSE
                    RAISE EXCEPTION 'verified user or same-tenant product connection context is required for contact changes'
                        USING ERRCODE = '42501';
                END IF;
            ELSE
                actor_identity_value := NULL;
                actor_membership_value := NULL;
                actor_type_value := 'system';
            END IF;

            SELECT organization_unit_id INTO event_org_unit
            FROM crm_profiles
            WHERE tenant_id = tenant_value AND id = profile_value;

            event_action := 'crm_contact_point.' || CASE TG_OP
                WHEN 'INSERT' THEN 'created'
                WHEN 'UPDATE' THEN 'updated'
                ELSE 'deleted'
            END;
            IF old_row IS NOT NULL THEN
                old_snapshot := jsonb_build_object(
                    'channel', old_row -> 'channel',
                    'verification_status', old_row -> 'verification_status',
                    'is_primary', old_row -> 'is_primary',
                    'encryption_key_id', old_row -> 'encryption_key_id'
                );
            END IF;
            IF new_row IS NOT NULL THEN
                new_snapshot := jsonb_build_object(
                    'channel', new_row -> 'channel',
                    'verification_status', new_row -> 'verification_status',
                    'is_primary', new_row -> 'is_primary',
                    'encryption_key_id', new_row -> 'encryption_key_id'
                );
            END IF;

            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                tenant_value, actor_type_value, actor_identity_value, actor_membership_value,
                event_action, 'crm_contact_point', current_row ->> 'id', event_org_unit,
                old_snapshot, new_snapshot,
                NULLIF(current_setting('app.correlation_id', true), '')::uuid
            );

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
    """)


def downgrade() -> None:
    op.execute("""
CREATE FUNCTION capture_crm_contact_point_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_row jsonb;
            old_row jsonb;
            new_row jsonb;
            old_snapshot jsonb;
            new_snapshot jsonb;
            tenant_value uuid;
            profile_value uuid;
            actor_identity_value uuid;
            actor_membership_value uuid;
            actor_type_value text;
            event_org_unit uuid;
            event_action text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                current_row := to_jsonb(NEW);
                new_row := current_row;
                old_row := NULL;
            ELSIF TG_OP = 'DELETE' THEN
                current_row := to_jsonb(OLD);
                new_row := NULL;
                old_row := current_row;
            ELSE
                current_row := to_jsonb(NEW);
                new_row := current_row;
                old_row := to_jsonb(OLD);
            END IF;

            tenant_value := (current_row ->> 'tenant_id')::uuid;
            profile_value := (current_row ->> 'profile_id')::uuid;
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL THEN
                IF NULLIF(current_setting('app.tenant_id', true), '')::uuid <> tenant_value THEN
                    RAISE EXCEPTION 'contact point tenant does not match verified context'
                        USING ERRCODE = '42501';
                END IF;
                actor_identity_value :=
                    NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
                actor_membership_value :=
                    NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
                IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                    RAISE EXCEPTION 'verified actor context is required for contact changes'
                        USING ERRCODE = '42501';
                END IF;
                actor_type_value := 'user';
            ELSE
                actor_identity_value := NULL;
                actor_membership_value := NULL;
                actor_type_value := 'system';
            END IF;

            SELECT organization_unit_id INTO event_org_unit
            FROM crm_profiles
            WHERE tenant_id = tenant_value AND id = profile_value;

            event_action := 'crm_contact_point.' || CASE TG_OP
                WHEN 'INSERT' THEN 'created'
                WHEN 'UPDATE' THEN 'updated'
                ELSE 'deleted'
            END;
            IF old_row IS NOT NULL THEN
                old_snapshot := jsonb_build_object(
                    'channel', old_row -> 'channel',
                    'verification_status', old_row -> 'verification_status',
                    'is_primary', old_row -> 'is_primary',
                    'encryption_key_id', old_row -> 'encryption_key_id'
                );
            END IF;
            IF new_row IS NOT NULL THEN
                new_snapshot := jsonb_build_object(
                    'channel', new_row -> 'channel',
                    'verification_status', new_row -> 'verification_status',
                    'is_primary', new_row -> 'is_primary',
                    'encryption_key_id', new_row -> 'encryption_key_id'
                );
            END IF;

            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                tenant_value, actor_type_value, actor_identity_value, actor_membership_value,
                event_action, 'crm_contact_point', current_row ->> 'id', event_org_unit,
                old_snapshot, new_snapshot,
                NULLIF(current_setting('app.correlation_id', true), '')::uuid
            );

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
