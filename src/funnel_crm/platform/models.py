Warning: truncated output (original token count: 28996)
Total output lines: 2335

"""Persistence models for tenant workspaces and organization units."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Identity,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base for SQLAlchemy persistence models."""


class Workspace(Base):
    """One customer's tenant boundary in the shared CRM platform."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "root_organization_type = 'root'",
            name="ck_workspaces_root_type",
        ),
        ForeignKeyConstraint(
            ["id", "root_organization_id", "root_organization_type"],
            [
                "organization_units.tenant_id",
                "organization_units.id",
                "organization_units.unit_type",
            ],
            name="fk_workspaces_root_organization_same_tenant",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    root_organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    root_organization_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="root", server_default="root"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class OrganizationUnit(Base):
    """A tenant-owned node in a customer's configurable organization tree."""

    __tablename__ = "organization_units"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_organization_units_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "id",
            "unit_type",
            name="uq_organization_units_tenant_id_type",
        ),
        CheckConstraint(
            "unit_type IN ('root', 'unit')",
            name="ck_organization_units_unit_type",
        ),
        CheckConstraint(
            "(unit_type = 'root' AND parent_id IS NULL) OR "
            "(unit_type = 'unit' AND parent_id IS NOT NULL)",
            name="ck_organization_units_root_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_organization_units_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_organization_units_parent_same_tenant",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_organization_units_one_root_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("unit_type = 'root'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class UserIdentity(Base):
    """Reference to an external authenticated identity; stores no credentials."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_user_identities_issuer_subject"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class WorkspaceMembership(Base):
    """A user's explicit membership in one workspace."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_workspace_memberships_tenant_id"),
        UniqueConstraint("tenant_id", "identity_id", name="uq_workspace_memberships_tenant_identity"),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_workspace_memberships_status",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_workspace_memberships_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["identity_id"], ["user_identities.id"],
            name="fk_workspace_memberships_identity", ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    identity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="invited", server_default="invited"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Role(Base):
    """A tenant-configurable bundle of explicit action permissions."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
        CheckConstraint("length(name) > 0", name="ck_roles_name_nonempty"),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_roles_workspace", ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class PermissionDefinition(Base):
    """Shared catalog entry for an explicit resource-and-action permission."""

    __tablename__ = "permission_definitions"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)


class RolePermission(Base):
    """A permission granted by a role within one tenant."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"],
            name="fk_role_permissions_role_same_tenant", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["permission_key"], ["permission_definitions.key"],
            name="fk_role_permissions_definition", ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    permission_key: Mapped[str] = mapped_column(String(160), primary_key=True)


class RoleAssignment(Base):
    """A role assigned to a membership at an explicit organization scope."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "membership_id", "role_id", "organization_unit_id",
            name="uq_role_assignments_membership_role_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_role_assignments_membership_same_tenant", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"],
            name="fk_role_assignments_role_same_tenant", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_role_assignments_scope_same_tenant", ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class TenantRecord(Base):
    """Tenant-owned anchor for records from CRM modules and connected products.

    Module-specific tables can extend this stable identity using the composite
    (tenant_id, id) key, so a record reference cannot cross workspaces.
    """

    __tablename__ = "tenant_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tenant_records_tenant_id"),
        UniqueConstraint(
            "tenant_id", "id", "record_type", name="uq_tenant_records_tenant_id_type"
        ),
        CheckConstraint("length(trim(record_type)) > 0", name="ck_tenant_records_type_nonempty"),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_tenant_records_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_tenant_records_org_same_tenant",
            ondelete="RESTRICT",
        ),
        Index("ix_tenant_records_tenant_type_created", "tenant_id", "record_type", "created_at"),
        Index("ix_tenant_records_tenant_org", "tenant_id", "organization_unit_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    record_type: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )


class AuditEvent(Base):
    """Append-only tenant audit event for security and organization changes."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user', 'system')",
            name="ck_audit_events_actor_kind",
        ),
        CheckConstraint(
            "(actor_kind = 'user' AND actor_identity_id IS NOT NULL "
            "AND actor_membership_id IS NOT NULL) OR "
            "(actor_kind = 'system' AND actor_identity_id IS NULL "
            "AND actor_membership_id IS NULL)",
            name="ck_audit_events_actor_shape",
        ),
        UniqueConstraint("tenant_id", "event_id", name="uq_audit_events_tenant_event"),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_audit_events_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_audit_events_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_audit_events_tenant_actor_time", "tenant_id", "actor_identity_id", "occurred_at"),
        Index("ix_audit_events_tenant_target_time", "tenant_id", "target_type", "target_key", "occurred_at"),
    )

    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action_key: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_key: Mapped[str] = mapped_column(String(250), nullable=False)
    organization_unit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )



class WorkspaceCRMSettings(Base):
    """Tenant-owned business-model configuration for a CRM workspace."""

    __tablename__ = "workspace_crm_settings"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(business_models) = 'array' "
            "AND jsonb_array_length(business_models) > 0",
            name="ck_workspace_crm_settings_business_models",
        ),
        CheckConstraint(
            "configuration_version > 0",
            name="ck_workspace_crm_settings_version_positive",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_workspace_crm_settings_workspace", ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    business_models: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["general"],
        server_default=text("""'["general"]'::jsonb"""),
    )
    configuration_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class CRMPipeline(Base):
    """Workspace-specific configurable stages for a record workflow."""

    __tablename__ = "crm_pipelines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_pipelines_tenant_id"),
        UniqueConstraint("tenant_id", "pipeline_key", name="uq_crm_pipelines_tenant_key"),
        CheckConstraint(
            "length(trim(pipeline_key)) > 0 AND length(trim(display_name)) > 0",
            name="ck_crm_pipelines_names_nonempty",
        ),
        CheckConstraint(
            "entity_kind IN ('person', 'organization', 'lead', 'opportunity')",
            name="ck_crm_pipelines_entity_kind",
        ),
        CheckConstraint(
            "jsonb_typeof(stages) = 'array' AND jsonb_array_length(stages) > 0",
            name="ck_crm_pipelines_stages_nonempty",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_pipelines_workspace", ondelete="CASCADE",
        ),
        Index("ix_crm_pipelines_tenant_entity", "tenant_id", "entity_kind"),
        Index(
            "uq_crm_pipelines_one_default_per_entity",
            "tenant_id",
            "entity_kind",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    pipeline_key: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class CRMCustomFieldDefinition(Base):
    """Typed tenant-owned custom field definition; values are stored separately."""

    __tablename__ = "crm_custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_custom_fields_tenant_id"),
        UniqueConstraint(
            "tenant_id", "entity_kind", "field_key",
            name="uq_crm_custom_fields_tenant_entity_key",
        ),
        CheckConstraint(
            "entity_kind IN ('person', 'organization', 'lead', 'opportunity')",
            name="ck_crm_custom_fields_entity_kind",
        ),
        CheckConstraint(
            "field_key ~ '^[a-z][a-z0-9_]{0,79}"+chr(36)+"'",
            name="ck_crm_custom_fields_key_format",
        ),
        CheckConstraint(
            "length(trim(display_name)) > 0",
            name="ck_crm_custom_fields_display_name",
        ),
        CheckConstraint(
            "value_type IN ('text', 'number', 'boolean', 'date', 'choice')",
            name="ck_crm_custom_fields_value_type",
        ),
        CheckConstraint(
            "jsonb_typeof(options) = 'array' AND "
            "((value_type = 'choice' AND jsonb_array_length(options) > 0) OR "
            "(value_type <> 'choice' AND jsonb_array_length(options) = 0))",
            name="ck_crm_custom_fields_options",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_custom_fields_workspace", ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    field_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    options: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class CRMProfileCustomFieldValue(Base):
    """Typed value attached to one profile and same-tenant field definition."""

    __tablename__ = "crm_profile_custom_field_values"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(value) IN ('string', 'number', 'boolean')",
            name="ck_crm_profile_custom_value_json_scalar",
        ),
        CheckConstraint(
            "octet_length(value::text) <= 8192",
            name="ck_crm_profile_custom_value_size",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_custom_value_profile_same_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "field_definition_id"],
            ["crm_custom_field_definitions.tenant_id", "crm_custom_field_definitions.id"],
            name="fk_crm_custom_value_definition_same_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "profile_id",
            "field_definition_id",
            name="uq_crm_custom_value_profile_definition",
        ),
        Index(
            "ix_crm_custom_values_tenant_profile",
            "tenant_id",
            "profile_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    field_definition_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class ProductConnection(Base):
    """Tenant-owned product connection with a one-time-issued API credential."""

    __tablename__ = "product_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_product_connections_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "credential_id",
            name="uq_product_connections_tenant_credential",
        ),
        CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_product_connections_source",
        ),
        CheckConstraint(
            "octet_length(credential_digest) = 32",
            name="ck_product_connections_credential_digest",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_event_types) = 'array' AND "
            "jsonb_array_length(allowed_event_types) BETWEEN 1 AND 50 AND "
            "octet_length(allowed_event_types::text) <= 8192",
            name="ck_product_connections_event_grants",
        ),
        CheckConstraint(
            "jsonb_typeof(contract_grants) = 'array' AND "
            "jsonb_array_length(contract_grants) BETWEEN 1 AND 50 AND "
            "octet_length(contract_grants::text) <= 8192",
            name="ck_product_connections_contract_grants",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_…16996 tokens truncated…s_uuid=True), nullable=True)
    source_outcome_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class CRMWorkItemOutcome(Base):
    """Human-recorded outcome for one lifecycle follow-up attempt."""

    __tablename__ = "crm_work_item_outcomes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_work_item_outcomes_tenant_id"),
        UniqueConstraint("tenant_id", "request_id", name="uq_crm_work_item_outcomes_request"),
        CheckConstraint(
            "outcome_code IN ('contact_made', 'no_contact', 'callback_requested', 'not_interested', 'other')",
            name="ck_crm_work_item_outcomes_code",
        ),
        CheckConstraint(
            "channel IN ('online', 'phone', 'store', 'field', 'support', 'campaign', 'other')",
            name="ck_crm_work_item_outcomes_channel",
        ),
        CheckConstraint("notes IS NULL OR length(notes) <= 2000",
                        name="ck_crm_work_item_outcomes_notes_length"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_work_item_outcomes_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_work_item_outcomes_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "work_item_id"],
            ["crm_work_items.tenant_id", "crm_work_items.id"],
            name="fk_crm_work_item_outcomes_item_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_work_item_outcomes_profile_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "recorded_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_item_outcomes_recorder_same_tenant", ondelete="RESTRICT"),
        Index("ix_crm_work_item_outcomes_tenant_org_time",
              "tenant_id", "organization_unit_id", "occurred_at"),
        Index("ix_crm_work_item_outcomes_tenant_item_time",
              "tenant_id", "work_item_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    work_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    recorded_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    outcome_code: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

class CRMProductCommerceEvent(Base):
    """Source fact for an explicitly recorded paid order or refund event."""

    __tablename__ = "crm_product_commerce_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_product", "source_event_id",
            name="uq_crm_product_commerce_events_source_event",
        ),
        CheckConstraint(
            "event_kind IN ('paid', 'refunded')",
            name="ck_crm_product_commerce_events_kind",
        ),
        CheckConstraint(
            "length(trim(order_reference)) BETWEEN 1 AND 200",
            name="ck_crm_product_commerce_events_order_reference",
        ),
        CheckConstraint(
            "amount >= 0 AND currency ~ '^[A-Z]{3}$'",
            name="ck_crm_product_commerce_events_money",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_product_commerce_events_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_product_commerce_events_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_product_commerce_events_profile_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "seller_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_product_commerce_events_seller_same_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id",
             "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_product_commerce_events_campaign_same_org",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_crm_product_commerce_events_tenant_org_time",
            "tenant_id", "organization_unit_id", "occurred_at",
        ),
        Index(
            "ix_crm_product_commerce_events_tenant_campaign_time",
            "tenant_id", "campaign_id", "occurred_at",
        ),
        Index(
            "ix_crm_product_commerce_events_tenant_seller_time",
            "tenant_id", "seller_membership_id", "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    seller_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_product: Mapped[str] = mapped_column(String(80), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    order_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )




class CRMSalesTarget(Base):
    """Organization and pipeline sales amount target for a date period and currency."""

    __tablename__ = "crm_sales_targets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_sales_targets_tenant_id"),
        UniqueConstraint(
            "tenant_id", "organization_unit_id", "pipeline_id",
            "period_start", "period_end", "currency",
            name="uq_crm_sales_targets_period_currency",
        ),
        CheckConstraint("target_amount > 0", name="ck_crm_sales_targets_positive_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_sales_targets_currency"),
        CheckConstraint("period_start <= period_end", name="ck_crm_sales_targets_period"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_sales_targets_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_sales_targets_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "pipeline_id"],
            ["crm_pipelines.tenant_id", "crm_pipelines.id"],
            name="fk_crm_sales_targets_pipeline_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_sales_targets_creator_same_tenant", ondelete="RESTRICT"),
        Index("ix_crm_sales_targets_tenant_org_period",
              "tenant_id", "organization_unit_id", "period_start", "period_end"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    pipeline_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CRMCommissionPlan(Base):
    """Percentage-of-net-sales rule scoped to an organization or one seller."""

    __tablename__ = "crm_commission_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_commission_plans_tenant_id"),
        CheckConstraint("rate_percent > 0 AND rate_percent <= 100", name="ck_crm_commission_plans_rate"),
        CheckConstraint("effective_start IS NULL OR effective_end IS NULL OR effective_start <= effective_end", name="ck_crm_commission_plans_effective_window"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_commission_plans_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_commission_plans_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "seller_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_commission_plans_seller_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_commission_plans_creator_same_tenant", ondelete="CASCADE"),
        Index("ix_crm_commission_plans_tenant_org", "tenant_id", "organization_unit_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    seller_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    effective_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CRMCommissionPlanVersion(Base):
    """Immutable rule values for one version of a commission plan."""

    __tablename__ = "crm_commission_plan_versions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_crm_commission_plan_versions_version_positive"),
        CheckConstraint("rate_percent > 0 AND rate_percent <= 100", name="ck_crm_commission_plan_versions_rate"),
        CheckConstraint("effective_start IS NULL OR effective_end IS NULL OR effective_start <= effective_end", name="ck_crm_commission_plan_versions_effective_window"),
        ForeignKeyConstraint(["tenant_id", "plan_id"],
            ["crm_commission_plans.tenant_id", "crm_commission_plans.id"],
            name="fk_crm_commission_plan_versions_plan_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "seller_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_commission_plan_versions_seller_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "changed_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_commission_plan_versions_actor_same_tenant", ondelete="CASCADE"),
        Index("ix_crm_commission_plan_versions_tenant_plan", "tenant_id", "plan_id", "version"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    effective_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CRMCommissionCalculation(Base):
    """Immutable calculation snapshot; it does not approve or pay commission."""

    __tablename__ = "crm_commission_calculations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_commission_calculations_tenant_id"),
        UniqueConstraint("tenant_id", "plan_id", "request_id", name="uq_crm_commission_calculations_request"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_commission_calculations_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "plan_id"],
            ["crm_commission_plans.tenant_id", "crm_commission_plans.id"],
            name="fk_crm_commission_calculations_plan_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "plan_id", "plan_version"],
            ["crm_commission_plan_versions.tenant_id", "crm_commission_plan_versions.plan_id", "crm_commission_plan_versions.version"],
            name="fk_crm_commission_calculations_plan_version_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_commission_calculations_creator_same_tenant", ondelete="CASCADE"),
        CheckConstraint("period_start <= period_end", name="ck_crm_commission_calculations_period"),
        Index("ix_crm_commission_calculations_tenant_plan", "tenant_id", "plan_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CRMCommissionCalculationRow(Base):
    """Currency-separated seller totals and exact source event lineage."""

    __tablename__ = "crm_commission_calculation_rows"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "calculation_id"],
            ["crm_commission_calculations.tenant_id", "crm_commission_calculations.id"],
            name="fk_crm_commission_rows_calculation_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "seller_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_commission_rows_seller_same_tenant", ondelete="CASCADE"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_commission_rows_currency"),
        UniqueConstraint("tenant_id", "calculation_id", "seller_membership_id", "currency",
            name="uq_crm_commission_rows_seller_currency"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    calculation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    seller_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class CRMProductCatalogItem(Base):
    """Workspace-owned product or service available for commercial offers."""

    __tablename__ = "crm_product_catalog_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_product_catalog_items_tenant_id"),
        UniqueConstraint("tenant_id", "organization_unit_id", "code", name="uq_crm_product_catalog_items_code"),
        CheckConstraint("item_type IN ('product', 'service')", name="ck_crm_product_catalog_items_type"),
        CheckConstraint("length(trim(code)) BETWEEN 1 AND 80", name="ck_crm_product_catalog_items_code"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="ck_crm_product_catalog_items_name"),
        CheckConstraint("category IS NULL OR length(trim(category)) BETWEEN 1 AND 120", name="ck_crm_product_catalog_items_category"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_product_catalog_items_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_product_catalog_items_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_product_catalog_items_creator_same_tenant", ondelete="CASCADE"),
        Index("ix_crm_product_catalog_items_tenant_org", "tenant_id", "organization_unit_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CRMProductCatalogPriceVersion(Base):
    """Append-only currency price version for a catalog item."""

    __tablename__ = "crm_product_catalog_price_versions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_crm_product_catalog_price_versions_version"),
        CheckConstraint("amount >= 0", name="ck_crm_product_catalog_price_versions_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_crm_product_catalog_price_versions_currency"),
        CheckConstraint("effective_start IS NULL OR effective_end IS NULL OR effective_start <= effective_end", name="ck_crm_product_catalog_price_versions_window"),
        ForeignKeyConstraint(["tenant_id", "item_id"],
            ["crm_product_catalog_items.tenant_id", "crm_product_catalog_items.id"],
            name="fk_crm_product_catalog_prices_item_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_product_catalog_prices_creator_same_tenant", ondelete="CASCADE"),
        Index("ix_crm_product_catalog_prices_tenant_item", "tenant_id", "item_id", "version"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
