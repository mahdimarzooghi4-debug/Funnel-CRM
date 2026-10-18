"""Allow verified product connections to author CRM audit events.

Revision ID: 20261018_16
Revises: 20261018_15
"""
from alembic import op

revision = "20261018_16"
down_revision = "20261018_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION capture_crm_audit_event()
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
            actor_identity_value uuid;
            actor_membership_value uuid;
            integration_connection_value uuid;
            actor_type_value text;
            event_target_type text;
            event_target_key text;
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
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM workspaces WHERE id = tenant_value
            ) THEN
                RETURN OLD;
            END IF;

            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
            integration_connection_value :=
                NULLIF(current_setting('app.integration_connection_id', true), '')::uuid;
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL THEN
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
                    RAISE EXCEPTION 'verified user or same-tenant product connection context is required for CRM changes'
                        USING ERRCODE = '42501';
                END IF;
            ELSE
                actor_identity_value := NULL;
                actor_membership_value := NULL;
                actor_type_value := 'system';
            END IF;

            event_target_type := CASE TG_TABLE_NAME
                WHEN 'workspace_crm_settings' THEN 'workspace_crm_settings'
                WHEN 'crm_pipelines' THEN 'crm_pipeline'
                WHEN 'crm_custom_field_definitions' THEN 'crm_custom_field_definition'
                ELSE 'crm_profile'
            END;
            event_target_key := COALESCE(current_row ->> 'id', current_row ->> 'tenant_id');
            event_org_unit := NULLIF(current_row ->> 'organization_unit_id', '')::uuid;
            event_action := event_target_type || '.' || CASE TG_OP
                WHEN 'INSERT' THEN 'created'
                WHEN 'UPDATE' THEN 'updated'
                ELSE 'deleted'
            END;

            IF TG_TABLE_NAME = 'workspace_crm_settings' THEN
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'business_models', old_row -> 'business_models',
                        'configuration_version', old_row -> 'configuration_version'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'business_models', new_row -> 'business_models',
                        'configuration_version', new_row -> 'configuration_version'
                    );
                END IF;
            ELSIF TG_TABLE_NAME = 'crm_pipelines' THEN
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'pipeline_key', old_row -> 'pipeline_key',
                        'entity_kind', old_row -> 'entity_kind',
                        'stages', old_row -> 'stages',
                        'is_default', old_row -> 'is_default'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'pipeline_key', new_row -> 'pipeline_key',
                        'entity_kind', new_row -> 'entity_kind',
                        'stages', new_row -> 'stages',
                        'is_default', new_row -> 'is_default'
                    );
                END IF;
            ELSIF TG_TABLE_NAME = 'crm_custom_field_definitions' THEN
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'entity_kind', old_row -> 'entity_kind',
                        'field_key', old_row -> 'field_key',
                        'value_type', old_row -> 'value_type',
                        'is_required', old_row -> 'is_required',
                        'is_active', old_row -> 'is_active'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'entity_kind', new_row -> 'entity_kind',
                        'field_key', new_row -> 'field_key',
                        'value_type', new_row -> 'value_type',
                        'is_required', new_row -> 'is_required',
                        'is_active', new_row -> 'is_active'
                    );
                END IF;
            ELSE
                -- Keep customer names out of the audit snapshots.
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'profile_kind', old_row -> 'profile_kind',
                        'lifecycle_stage', old_row -> 'lifecycle_stage'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'profile_kind', new_row -> 'profile_kind',
                        'lifecycle_stage', new_row -> 'lifecycle_stage'
                    );
                END IF;
            END IF;

            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                tenant_value, actor_type_value, actor_identity_value, actor_membership_value,
                event_action, event_target_type, event_target_key, event_org_unit,
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
CREATE FUNCTION capture_crm_audit_event()
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
            actor_identity_value uuid;
            actor_membership_value uuid;
            actor_type_value text;
            event_target_type text;
            event_target_key text;
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
                    RAISE EXCEPTION 'verified actor context is required for CRM changes'
                        USING ERRCODE = '42501';
                END IF;
                actor_type_value := 'user';
            ELSE
                actor_identity_value := NULL;
                actor_membership_value := NULL;
                actor_type_value := 'system';
            END IF;

            event_target_type := CASE TG_TABLE_NAME
                WHEN 'workspace_crm_settings' THEN 'workspace_crm_settings'
                WHEN 'crm_pipelines' THEN 'crm_pipeline'
                WHEN 'crm_custom_field_definitions' THEN 'crm_custom_field_definition'
                ELSE 'crm_profile'
            END;
            event_target_key := COALESCE(current_row ->> 'id', current_row ->> 'tenant_id');
            event_org_unit := NULLIF(current_row ->> 'organization_unit_id', '')::uuid;
            event_action := event_target_type || '.' || CASE TG_OP
                WHEN 'INSERT' THEN 'created'
                WHEN 'UPDATE' THEN 'updated'
                ELSE 'deleted'
            END;

            IF TG_TABLE_NAME = 'workspace_crm_settings' THEN
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'business_models', old_row -> 'business_models',
                        'configuration_version', old_row -> 'configuration_version'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'business_models', new_row -> 'business_models',
                        'configuration_version', new_row -> 'configuration_version'
                    );
                END IF;
            ELSIF TG_TABLE_NAME = 'crm_pipelines' THEN
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'pipeline_key', old_row -> 'pipeline_key',
                        'entity_kind', old_row -> 'entity_kind',
                        'stages', old_row -> 'stages',
                        'is_default', old_row -> 'is_default'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'pipeline_key', new_row -> 'pipeline_key',
                        'entity_kind', new_row -> 'entity_kind',
                        'stages', new_row -> 'stages',
                        'is_default', new_row -> 'is_default'
                    );
                END IF;
            ELSIF TG_TABLE_NAME = 'crm_custom_field_definitions' THEN
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'entity_kind', old_row -> 'entity_kind',
                        'field_key', old_row -> 'field_key',
                        'value_type', old_row -> 'value_type',
                        'is_required', old_row -> 'is_required',
                        'is_active', old_row -> 'is_active'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'entity_kind', new_row -> 'entity_kind',
                        'field_key', new_row -> 'field_key',
                        'value_type', new_row -> 'value_type',
                        'is_required', new_row -> 'is_required',
                        'is_active', new_row -> 'is_active'
                    );
                END IF;
            ELSE
                -- Keep customer names out of the audit snapshots.
                IF old_row IS NOT NULL THEN
                    old_snapshot := jsonb_build_object(
                        'profile_kind', old_row -> 'profile_kind',
                        'lifecycle_stage', old_row -> 'lifecycle_stage'
                    );
                END IF;
                IF new_row IS NOT NULL THEN
                    new_snapshot := jsonb_build_object(
                        'profile_kind', new_row -> 'profile_kind',
                        'lifecycle_stage', new_row -> 'lifecycle_stage'
                    );
                END IF;
            END IF;

            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                tenant_value, actor_type_value, actor_identity_value, actor_membership_value,
                event_action, event_target_type, event_target_key, event_org_unit,
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
