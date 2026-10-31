"""Record provenance and event idempotency for product-reported consent.

Revision ID: 20261031_83
Revises: 20261031_82
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_83"
down_revision = "20261031_82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_communication_consent_events",
        sa.Column("source_product", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "crm_communication_consent_events",
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_consent_source_pair",
        "crm_communication_consent_events",
        "(source_product IS NULL) = (source_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_crm_consent_source_product",
        "crm_communication_consent_events",
        "source_product IS NULL OR source_product ~ '^[a-z0-9][a-z0-9._-]{1,79}$'",
    )
    op.create_index(
        "uq_crm_consent_source_event",
        "crm_communication_consent_events",
        ["tenant_id", "source_product", "source_event_id"],
        unique=True,
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION capture_crm_communication_consent_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $consent$
        DECLARE
            actor_identity_value uuid;
            actor_membership_value uuid;
            integration_connection_value uuid;
            event_org_unit uuid;
        BEGIN
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NULL
               OR NULLIF(current_setting('app.tenant_id', true), '')::uuid <> NEW.tenant_id THEN
                RAISE EXCEPTION 'verified tenant context is required for consent events'
                    USING ERRCODE = '42501';
            END IF;

            SELECT organization_unit_id INTO event_org_unit
            FROM crm_profiles
            WHERE tenant_id = NEW.tenant_id AND id = NEW.profile_id;

            integration_connection_value :=
                NULLIF(current_setting('app.integration_connection_id', true), '')::uuid;
            IF NEW.source_event_id IS NOT NULL THEN
                IF integration_connection_value IS NULL OR NOT EXISTS (
                    SELECT 1
                    FROM product_connections
                    WHERE tenant_id = NEW.tenant_id
                      AND id = integration_connection_value
                      AND source_product = NEW.source_product
                      AND allowed_event_types @> '["customer.communication_consent.changed"]'::jsonb
                      AND contract_grants @> jsonb_build_array(jsonb_build_object('contract_name', 'crm.customer.communication_consent', 'contract_version', 1))
                ) THEN
                    RAISE EXCEPTION 'verified product connection context is required for consent events'
                        USING ERRCODE = '42501';
                END IF;

                INSERT INTO audit_events (
                    tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                    action_key, target_type, target_key, organization_unit_id,
                    before_state, after_state, correlation_id
                ) VALUES (
                    NEW.tenant_id, 'system', NULL, NULL,
                    'integration.communication_consent.recorded',
                    'crm_communication_consent', NEW.id::text, event_org_unit,
                    NULL,
                    jsonb_build_object(
                        'source_product', NEW.source_product,
                        'source_event_id', NEW.source_event_id,
                        'purpose_key', NEW.purpose_key,
                        'channel', NEW.channel,
                        'decision', NEW.decision,
                        'policy_version', NEW.policy_version
                    ),
                    NULLIF(current_setting('app.correlation_id', true), '')::uuid
                );
                RETURN NEW;
            END IF;

            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
            IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                RAISE EXCEPTION 'verified actor context is required for consent events'
                    USING ERRCODE = '42501';
            END IF;

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
        $consent$
        """
    )



def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION capture_crm_communication_consent_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $consent$
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
        $consent$
        """
    )

    op.drop_index(
        "uq_crm_consent_source_event",
        table_name="crm_communication_consent_events",
    )
    op.drop_constraint(
        "ck_crm_consent_source_product",
        "crm_communication_consent_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_crm_consent_source_pair",
        "crm_communication_consent_events",
        type_="check",
    )
    op.drop_column("crm_communication_consent_events", "source_event_id")
    op.drop_column("crm_communication_consent_events", "source_product")
