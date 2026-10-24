"""Persistence models for tenant workspaces and organization units."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Identity,
    LargeBinary,
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
            "field_key ~ '^[a-z][a-z0-9_]{0,79}$'",
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


class CRMProfileSegment(Base):
    """Saved, tenant-owned live audience definition over customer profile fields."""

    __tablename__ = "crm_profile_segments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_profile_segments_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "organization_unit_id",
            "name",
            name="uq_crm_profile_segments_tenant_org_name",
        ),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_crm_profile_segments_name",
        ),
        CheckConstraint(
            "jsonb_typeof(criteria) = 'object' AND octet_length(criteria::text) <= 4096",
            name="ck_crm_profile_segments_criteria",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_profile_segments_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_profile_segments_org_same_tenant",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_crm_profile_segments_tenant_org_active",
            "tenant_id",
            "organization_unit_id",
            "is_active",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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


class CRMProfile(Base):
    """Tenant-owned person or organization profile anchored to a tenant record."""

    __tablename__ = "crm_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_profiles_tenant_id"),
        CheckConstraint(
            "record_type = 'crm_profile'",
            name="ck_crm_profiles_record_type",
        ),
        CheckConstraint(
            "profile_kind IN ('person', 'organization')",
            name="ck_crm_profiles_profile_kind",
        ),
        CheckConstraint(
            "length(trim(display_name)) BETWEEN 1 AND 240",
            name="ck_crm_profiles_display_name",
        ),
        CheckConstraint(
            "length(trim(lifecycle_stage)) BETWEEN 1 AND 80",
            name="ck_crm_profiles_lifecycle_stage",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "id", "record_type"],
            ["tenant_records.tenant_id", "tenant_records.id", "tenant_records.record_type"],
            name="fk_crm_profiles_record_anchor", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_profiles_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "merged_into_profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_profiles_merge_target_same_tenant",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "merged_into_profile_id IS NULL OR merged_into_profile_id <> id",
            name="ck_crm_profiles_not_merged_into_self",
        ),
        Index("ix_crm_profiles_tenant_kind_stage", "tenant_id", "profile_kind", "lifecycle_stage"),
        Index("ix_crm_profiles_tenant_merge_target", "tenant_id", "merged_into_profile_id"),
        Index("ix_crm_profiles_tenant_archived", "tenant_id", "archived_at"),
        Index("ix_crm_profiles_tenant_org", "tenant_id", "organization_unit_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    record_type: Mapped[str] = mapped_column(
        String(80), nullable=False, default="crm_profile", server_default="crm_profile"
    )
    profile_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    lifecycle_stage: Mapped[str] = mapped_column(
        String(80), nullable=False, default="lead", server_default="lead"
    )
    merged_into_profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )



class CRMContactPoint(Base):
    """Encrypted customer contact value; cleartext never enters the database."""

    __tablename__ = "crm_contact_points"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('email', 'phone', 'postal_address', 'social_handle', 'website')",
            name="ck_crm_contact_points_channel",
        ),
        CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'invalid')",
            name="ck_crm_contact_points_verification_status",
        ),
        CheckConstraint(
            "length(trim(encryption_key_id)) BETWEEN 1 AND 64",
            name="ck_crm_contact_points_key_id",
        ),
        CheckConstraint(
            "octet_length(encrypted_value) BETWEEN 29 AND 4096",
            name="ck_crm_contact_points_ciphertext_size",
        ),
        CheckConstraint(
            "(match_fingerprint IS NULL AND fingerprint_key_id IS NULL) OR "
            "(octet_length(match_fingerprint) = 32 AND "
            "length(trim(fingerprint_key_id)) BETWEEN 1 AND 64)",
            name="ck_crm_contact_points_fingerprint_pair",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_contact_points_profile_same_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_crm_contact_points_tenant_profile", "tenant_id", "profile_id"),
        Index(
            "ix_crm_contact_points_blind_match",
            "tenant_id",
            "channel",
            "fingerprint_key_id",
            "match_fingerprint",
        ),
        Index(
            "uq_crm_contact_points_one_primary_per_channel",
            "tenant_id",
            "profile_id",
            "channel",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_key_id: Mapped[str | None] = mapped_column(String(64))
    match_fingerprint: Mapped[bytes | None] = mapped_column(LargeBinary)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified", server_default="unverified"
    )
    is_primary: Mapped[bool] = mapped_column(
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

class CRMCommunicationConsentEvent(Base):
    """Append-only, purpose- and channel-specific communication decision."""

    __tablename__ = "crm_communication_consent_events"
    __table_args__ = (
        CheckConstraint(
            "purpose_key ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_consent_purpose_key",
        ),
        CheckConstraint(
            "channel IN ('email', 'phone', 'postal_address', 'social_handle', 'website')",
            name="ck_crm_consent_channel",
        ),
        CheckConstraint(
            "decision IN ('granted', 'withdrawn')",
            name="ck_crm_consent_decision",
        ),
        CheckConstraint(
            "length(trim(policy_version)) BETWEEN 1 AND 64",
            name="ck_crm_consent_policy_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_consent_profile_same_tenant",
            ondelete="CASCADE",
        ),
        Index(
            "ix_crm_consent_latest_by_scope",
            "tenant_id",
            "profile_id",
            "purpose_key",
            "channel",
            "recorded_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purpose_key: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
