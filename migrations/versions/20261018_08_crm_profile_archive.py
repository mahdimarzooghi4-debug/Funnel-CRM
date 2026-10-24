"""Add soft archival and restore audit events for CRM profiles.

Revision ID: 20261018_08
Revises: 20261018_07
"""

from alembic import op
import sqlalchemy as sa

revision = "20261018_08"
down_revision = "20261018_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_profiles",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_crm_profiles_tenant_archived",
        "crm_profiles",
        ["tenant_id", "archived_at"],
    )
    op.execute(
        """
        CREATE FUNCTION capture_crm_profile_archive_audit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            actor_identity_value uuid;
            actor_membership_value uuid;
            action_value text;
        BEGIN
            IF OLD.archived_at IS NOT DISTINCT FROM NEW.archived_at THEN
                RETURN NEW;
            END IF;
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NULL
               OR NULLIF(current_setting('app.tenant_id', true), '')::uuid <> NEW.tenant_id THEN
                RAISE EXCEPTION 'verified tenant context is required for CRM profile archive'
                    USING ERRCODE = '42501';
            END IF;
            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
            IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                RAISE EXCEPTION 'verified actor context is required for CRM profile archive'
                    USING ERRCODE = '42501';
            END IF;

            action_value := CASE
                WHEN NEW.archived_at IS NULL THEN 'crm_profile.restored'
                ELSE 'crm_profile.archived'
            END;
            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                NEW.tenant_id, 'user', actor_identity_value, actor_membership_value,
                action_value, 'crm_profile_archive', NEW.id::text, NEW.organization_unit_id,
                jsonb_build_object('archived_at', OLD.archived_at),
                jsonb_build_object('archived_at', NEW.archived_at),
                NULLIF(current_setting('app.correlation_id', true), '')::uuid
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_profile_archive_audit
        AFTER UPDATE OF archived_at ON crm_profiles
        FOR EACH ROW EXECUTE FUNCTION capture_crm_profile_archive_audit()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER crm_profile_archive_audit ON crm_profiles")
    op.execute("DROP FUNCTION capture_crm_profile_archive_audit()")
    op.drop_index("ix_crm_profiles_tenant_archived", table_name="crm_profiles")
    op.drop_column("crm_profiles", "archived_at")
