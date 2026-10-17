"""Add encrypted customer contact points and scoped permissions.

Revision ID: 20261018_03
Revises: 20261018_02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_03"
down_revision = "20261018_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_contact_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_id", sa.String(length=64), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "channel IN ('email', 'phone', 'postal_address', 'social_handle', 'website')",
            name="ck_crm_contact_points_channel",
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'invalid')",
            name="ck_crm_contact_points_verification_status",
        ),
        sa.CheckConstraint(
            "length(trim(encryption_key_id)) BETWEEN 1 AND 64",
            name="ck_crm_contact_points_key_id",
        ),
        sa.CheckConstraint(
            "octet_length(encrypted_value) BETWEEN 29 AND 2048",
            name="ck_crm_contact_points_ciphertext_size",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_contact_points_profile_same_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_contact_points_tenant_profile",
        "crm_contact_points",
        ["tenant_id", "profile_id"],
    )
    op.create_index(
        "uq_crm_contact_points_one_primary_per_channel",
        "crm_contact_points",
        ["tenant_id", "profile_id", "channel"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.execute("ALTER TABLE crm_contact_points ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_contact_points FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON crm_contact_points
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        INSERT INTO permission_definitions (key, description) VALUES
            ('crm.contact_point:view', 'View encrypted customer contact points'),
            ('crm.contact_point:create', 'Create encrypted customer contact points'),
            ('crm.contact_point:update', 'Update customer contact point metadata')
        ON CONFLICT (key) DO NOTHING
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_audit_contact_points
        AFTER INSERT OR UPDATE OR DELETE ON crm_contact_points
        FOR EACH ROW EXECUTE FUNCTION capture_crm_contact_point_audit_event()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER crm_audit_contact_points ON crm_contact_points")
    op.execute("DROP FUNCTION capture_crm_contact_point_audit_event()")
    op.execute("DROP POLICY tenant_isolation ON crm_contact_points")
    op.execute("ALTER TABLE crm_contact_points NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_contact_points DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "uq_crm_contact_points_one_primary_per_channel",
        table_name="crm_contact_points",
    )
    op.drop_index("ix_crm_contact_points_tenant_profile", table_name="crm_contact_points")
    op.drop_table("crm_contact_points")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_key IN (
            'crm.contact_point:view',
            'crm.contact_point:create',
            'crm.contact_point:update'
        )
        """
    )
    op.execute(
        """
        DELETE FROM permission_definitions
        WHERE key IN (
            'crm.contact_point:view',
            'crm.contact_point:create',
            'crm.contact_point:update'
        )
        """
    )
