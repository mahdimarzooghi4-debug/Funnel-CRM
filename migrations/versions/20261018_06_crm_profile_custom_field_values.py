"""Add typed custom values for customer profiles.

Revision ID: 20261018_06
Revises: 20261018_05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_06"
down_revision = "20261018_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_profile_custom_field_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(value) IN ('string', 'number', 'boolean')",
            name="ck_crm_profile_custom_value_json_scalar",
        ),
        sa.CheckConstraint(
            "octet_length(value::text) <= 8192",
            name="ck_crm_profile_custom_value_size",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_custom_value_profile_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "field_definition_id"],
            ["crm_custom_field_definitions.tenant_id", "crm_custom_field_definitions.id"],
            name="fk_crm_custom_value_definition_same_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "profile_id",
            "field_definition_id",
            name="uq_crm_custom_value_profile_definition",
        ),
    )
    op.create_index(
        "ix_crm_custom_values_tenant_profile",
        "crm_profile_custom_field_values",
        ["tenant_id", "profile_id"],
    )
    op.execute(
        "ALTER TABLE crm_profile_custom_field_values ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE crm_profile_custom_field_values FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_profile_custom_field_values
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        INSERT INTO permission_definitions (key, description) VALUES
            ('crm.custom_field:view', 'View custom values on customer profiles'),
            ('crm.custom_field:update', 'Set custom values on customer profiles')
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_crm_profile_custom_field_value()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            profile_kind text;
            definition_kind text;
            field_active boolean;
        BEGIN
            SELECT p.profile_kind INTO profile_kind
            FROM crm_profiles AS p
            WHERE p.tenant_id = NEW.tenant_id AND p.id = NEW.profile_id;

            SELECT d.entity_kind, d.is_active INTO definition_kind, field_active
            FROM crm_custom_field_definitions AS d
            WHERE d.tenant_id = NEW.tenant_id AND d.id = NEW.field_definition_id;

            IF profile_kind IS NULL OR definition_kind IS NULL
               OR profile_kind <> definition_kind OR NOT field_active THEN
                RAISE EXCEPTION 'custom field does not apply to this CRM profile'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_validate_custom_field_value
        BEFORE INSERT OR UPDATE ON crm_profile_custom_field_values
        FOR EACH ROW EXECUTE FUNCTION validate_crm_profile_custom_field_value()
        """
    )
    op.execute(
        """
        CREATE FUNCTION capture_crm_profile_custom_field_value_audit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_row jsonb;
            field_key_value text;
            value_type_value text;
            tenant_value uuid;
            profile_value uuid;
            actor_identity_value uuid;
            actor_membership_value uuid;
            event_org_unit uuid;
            event_action text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                current_row := to_jsonb(OLD);
            ELSE
                current_row := to_jsonb(NEW);
            END IF;
            tenant_value := (current_row ->> 'tenant_id')::uuid;
            profile_value := (current_row ->> 'profile_id')::uuid;

            IF NULLIF(current_setting('app.tenant_id', true), '') IS NULL
               OR NULLIF(current_setting('app.tenant_id', true), '')::uuid <> tenant_value THEN
                RAISE EXCEPTION 'verified tenant context is required for custom field changes'
                    USING ERRCODE = '42501';
            END IF;
            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
            IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                RAISE EXCEPTION 'verified actor context is required for custom field changes'
                    USING ERRCODE = '42501';
            END IF;

            SELECT d.field_key, d.value_type
            INTO field_key_value, value_type_value
            FROM crm_custom_field_definitions AS d
            WHERE d.tenant_id = tenant_value
              AND d.id = (current_row ->> 'field_definition_id')::uuid;

            SELECT organization_unit_id INTO event_org_unit
            FROM crm_profiles
            WHERE tenant_id = tenant_value AND id = profile_value;

            event_action := 'crm.custom_field_value.' || CASE TG_OP
                WHEN 'INSERT' THEN 'created'
                WHEN 'UPDATE' THEN 'updated'
                ELSE 'deleted'
            END;
            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                tenant_value, 'user', actor_identity_value, actor_membership_value,
                event_action, 'crm_profile_custom_field_value',
                current_row ->> 'id', event_org_unit,
                CASE WHEN TG_OP = 'INSERT' THEN NULL
                    ELSE jsonb_build_object(
                        'field_key', field_key_value,
                        'value_type', value_type_value,
                        'is_set', true
                    ) END,
                CASE WHEN TG_OP = 'DELETE' THEN NULL
                    ELSE jsonb_build_object(
                        'field_key', field_key_value,
                        'value_type', value_type_value,
                        'is_set', true
                    ) END,
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
    op.execute(
        """
        CREATE TRIGGER crm_audit_custom_field_values
        AFTER INSERT OR UPDATE OR DELETE ON crm_profile_custom_field_values
        FOR EACH ROW EXECUTE FUNCTION capture_crm_profile_custom_field_value_audit()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER crm_audit_custom_field_values ON crm_profile_custom_field_values"
    )
    op.execute("DROP FUNCTION capture_crm_profile_custom_field_value_audit()")
    op.execute(
        "DROP TRIGGER crm_validate_custom_field_value ON crm_profile_custom_field_values"
    )
    op.execute("DROP FUNCTION validate_crm_profile_custom_field_value()")
    op.execute(
        "DROP POLICY tenant_isolation ON crm_profile_custom_field_values"
    )
    op.execute(
        "ALTER TABLE crm_profile_custom_field_values NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE crm_profile_custom_field_values DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_crm_custom_values_tenant_profile",
        table_name="crm_profile_custom_field_values",
    )
    op.drop_table("crm_profile_custom_field_values")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_key IN ('crm.custom_field:view', 'crm.custom_field:update')
        """
    )
    op.execute(
        """
        DELETE FROM permission_definitions
        WHERE key IN ('crm.custom_field:view', 'crm.custom_field:update')
        """
    )
