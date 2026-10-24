"""Create workspace CRM configuration and tenant-owned CRM profiles.

Revision ID: 20261018_01
Revises: 20261017_05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_01"
down_revision = "20261017_05"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "workspace_crm_settings",
    "crm_pipelines",
    "crm_custom_field_definitions",
    "crm_profiles",
)


def _enable_tenant_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{table_name}"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def upgrade() -> None:
    op.create_table(
        "workspace_crm_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "business_models",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'["general"]'::jsonb"""),
        ),
        sa.Column(
            "configuration_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(business_models) = 'array' "
            "AND jsonb_array_length(business_models) > 0",
            name="ck_workspace_crm_settings_business_models",
        ),
        sa.CheckConstraint(
            "configuration_version > 0",
            name="ck_workspace_crm_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_workspace_crm_settings_workspace", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.execute(
        """
        INSERT INTO workspace_crm_settings (tenant_id)
        SELECT id FROM workspaces
        """
    )

    op.create_table(
        "crm_pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_key", sa.String(length=80), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("stages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "length(trim(pipeline_key)) > 0 AND length(trim(display_name)) > 0",
            name="ck_crm_pipelines_names_nonempty",
        ),
        sa.CheckConstraint(
            "entity_kind IN ('person', 'organization', 'lead', 'opportunity')",
            name="ck_crm_pipelines_entity_kind",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(stages) = 'array' AND jsonb_array_length(stages) > 0",
            name="ck_crm_pipelines_stages_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_pipelines_workspace", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_pipelines_tenant_id"),
        sa.UniqueConstraint("tenant_id", "pipeline_key", name="uq_crm_pipelines_tenant_key"),
    )
    op.create_index("ix_crm_pipelines_tenant_entity", "crm_pipelines", ["tenant_id", "entity_kind"])
    op.create_index(
        "uq_crm_pipelines_one_default_per_entity",
        "crm_pipelines",
        ["tenant_id", "entity_kind"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "crm_custom_field_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("field_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "entity_kind IN ('person', 'organization', 'lead', 'opportunity')",
            name="ck_crm_custom_fields_entity_kind",
        ),
        sa.CheckConstraint(
            "field_key ~ '^[a-z][a-z0-9_]{0,79}$'",
            name="ck_crm_custom_fields_key_format",
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0",
            name="ck_crm_custom_fields_display_name",
        ),
        sa.CheckConstraint(
            "value_type IN ('text', 'number', 'boolean', 'date', 'choice')",
            name="ck_crm_custom_fields_value_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array' AND "
            "((value_type = 'choice' AND jsonb_array_length(options) > 0) OR "
            "(value_type <> 'choice' AND jsonb_array_length(options) = 0))",
            name="ck_crm_custom_fields_options",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_custom_fields_workspace", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_custom_fields_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "entity_kind", "field_key",
            name="uq_crm_custom_fields_tenant_entity_key",
        ),
    )

    op.create_table(
        "crm_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "record_type", sa.String(length=80), nullable=False,
            server_default=sa.text("'crm_profile'"),
        ),
        sa.Column("profile_kind", sa.String(length=24), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column(
            "lifecycle_stage", sa.String(length=80), nullable=False,
            server_default=sa.text("'lead'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("record_type = 'crm_profile'", name="ck_crm_profiles_record_type"),
        sa.CheckConstraint(
            "profile_kind IN ('person', 'organization')",
            name="ck_crm_profiles_profile_kind",
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) BETWEEN 1 AND 240",
            name="ck_crm_profiles_display_name",
        ),
        sa.CheckConstraint(
            "length(trim(lifecycle_stage)) BETWEEN 1 AND 80",
            name="ck_crm_profiles_lifecycle_stage",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "id", "record_type"],
            ["tenant_records.tenant_id", "tenant_records.id", "tenant_records.record_type"],
            name="fk_crm_profiles_record_anchor", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_profiles_org_same_tenant", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_profiles_tenant_id"),
    )
    op.create_index(
        "ix_crm_profiles_tenant_kind_stage",
        "crm_profiles",
        ["tenant_id", "profile_kind", "lifecycle_stage"],
    )
    op.create_index(
        "ix_crm_profiles_tenant_org", "crm_profiles", ["tenant_id", "organization_unit_id"]
    )

    for table_name in TENANT_TABLES:
        _enable_tenant_rls(table_name)

    op.execute(
        """
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
        """
    )
    for table_name in TENANT_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER crm_audit_{table_name}
            AFTER INSERT OR UPDATE OR DELETE ON "{table_name}"
            FOR EACH ROW EXECUTE FUNCTION capture_crm_audit_event()
            """
        )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.execute(f'DROP TRIGGER crm_audit_{table_name} ON "{table_name}"')
        op.execute(f'DROP POLICY tenant_isolation ON "{table_name}"')
        op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP FUNCTION capture_crm_audit_event()")
    op.drop_index("ix_crm_profiles_tenant_org", table_name="crm_profiles")
    op.drop_index("ix_crm_profiles_tenant_kind_stage", table_name="crm_profiles")
    op.drop_table("crm_profiles")
    op.drop_table("crm_custom_field_definitions")
    op.drop_index("uq_crm_pipelines_one_default_per_entity", table_name="crm_pipelines")
    op.drop_index("ix_crm_pipelines_tenant_entity", table_name="crm_pipelines")
    op.drop_table("crm_pipelines")
    op.drop_table("workspace_crm_settings")
