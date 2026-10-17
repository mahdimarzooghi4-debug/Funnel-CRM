"""Add reversible, audited CRM profile merge links.

Revision ID: 20261018_07
Revises: 20261018_06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261018_07"
down_revision = "20261018_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_profiles",
        sa.Column("merged_into_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_crm_profiles_not_merged_into_self",
        "crm_profiles",
        "merged_into_profile_id IS NULL OR merged_into_profile_id <> id",
    )
    op.create_foreign_key(
        "fk_crm_profiles_merge_target_same_tenant",
        "crm_profiles",
        "crm_profiles",
        ["tenant_id", "merged_into_profile_id"],
        ["tenant_id", "id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_crm_profiles_tenant_merge_target",
        "crm_profiles",
        ["tenant_id", "merged_into_profile_id"],
    )
    op.execute(
        """
        CREATE FUNCTION capture_crm_profile_merge_audit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            actor_identity_value uuid;
            actor_membership_value uuid;
            action_value text;
        BEGIN
            IF OLD.merged_into_profile_id IS NOT DISTINCT FROM NEW.merged_into_profile_id THEN
                RETURN NEW;
            END IF;
            IF NULLIF(current_setting('app.tenant_id', true), '') IS NULL
               OR NULLIF(current_setting('app.tenant_id', true), '')::uuid <> NEW.tenant_id THEN
                RAISE EXCEPTION 'verified tenant context is required for CRM profile merge'
                    USING ERRCODE = '42501';
            END IF;
            actor_identity_value :=
                NULLIF(current_setting('app.actor_identity_id', true), '')::uuid;
            actor_membership_value :=
                NULLIF(current_setting('app.actor_membership_id', true), '')::uuid;
            IF actor_identity_value IS NULL OR actor_membership_value IS NULL THEN
                RAISE EXCEPTION 'verified actor context is required for CRM profile merge'
                    USING ERRCODE = '42501';
            END IF;

            action_value := CASE
                WHEN NEW.merged_into_profile_id IS NULL THEN 'crm_profile.unmerged'
                ELSE 'crm_profile.merged'
            END;
            INSERT INTO audit_events (
                tenant_id, actor_kind, actor_identity_id, actor_membership_id,
                action_key, target_type, target_key, organization_unit_id,
                before_state, after_state, correlation_id
            ) VALUES (
                NEW.tenant_id, 'user', actor_identity_value, actor_membership_value,
                action_value, 'crm_profile_merge', NEW.id::text, NEW.organization_unit_id,
                jsonb_build_object('merged_into_profile_id', OLD.merged_into_profile_id),
                jsonb_build_object('merged_into_profile_id', NEW.merged_into_profile_id),
                NULLIF(current_setting('app.correlation_id', true), '')::uuid
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER crm_profile_merge_audit
        AFTER UPDATE OF merged_into_profile_id ON crm_profiles
        FOR EACH ROW EXECUTE FUNCTION capture_crm_profile_merge_audit()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER crm_profile_merge_audit ON crm_profiles")
    op.execute("DROP FUNCTION capture_crm_profile_merge_audit()")
    op.drop_index("ix_crm_profiles_tenant_merge_target", table_name="crm_profiles")
    op.drop_constraint(
        "fk_crm_profiles_merge_target_same_tenant",
        "crm_profiles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_crm_profiles_not_merged_into_self",
        "crm_profiles",
        type_="check",
    )
    op.drop_column("crm_profiles", "merged_into_profile_id")
