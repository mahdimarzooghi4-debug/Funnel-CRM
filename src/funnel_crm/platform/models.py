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
            name="fk_product_connections_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_product_connections_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    credential_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    credential_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_product: Mapped[str] = mapped_column(String(80), nullable=False)
    allowed_event_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    contract_grants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationEventInbox(Base):
    """Durable tenant-scoped receipt for an event from a verified product connection."""

    __tablename__ = "integration_event_inbox"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_product",
            "event_id",
            name="uq_integration_event_inbox_idempotency",
        ),
        CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_integration_event_inbox_source",
        ),
        CheckConstraint(
            "length(trim(event_type)) BETWEEN 3 AND 120",
            name="ck_integration_event_inbox_event_type",
        ),
        CheckConstraint(
            "length(trim(contract_name)) BETWEEN 2 AND 80 AND contract_version > 0",
            name="ck_integration_event_inbox_contract",
        ),
        CheckConstraint(
            "octet_length(event_digest) = 32",
            name="ck_integration_event_inbox_digest",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 131072",
            name="ck_integration_event_inbox_payload",
        ),
        CheckConstraint(
            "(payload_key_id IS NULL) = (encrypted_payload IS NULL)",
            name="ck_integration_event_inbox_payload_cipher_pair",
        ),
        CheckConstraint(
            "payload_key_id IS NULL OR payload = '{}'::jsonb",
            name="ck_integration_event_inbox_cipher_has_empty_legacy_payload",
        ),
        CheckConstraint(
            "processing_status IN ('received', 'processing', 'processed', 'failed')",
            name="ck_integration_event_inbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_integration_event_inbox_attempt_count",
        ),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)",
            name="ck_integration_event_inbox_lease_pair",
        ),
        CheckConstraint(
            "processing_status <> 'processing' OR lease_token IS NOT NULL",
            name="ck_integration_event_inbox_processing_lease",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_integration_event_inbox_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_integration_event_inbox_tenant_received", "tenant_id", "received_at"),
        Index(
            "ix_integration_event_inbox_received_pending",
            "received_at",
            postgresql_where=text("processing_status = 'received'"),
        ),
        Index(
            "ix_integration_event_inbox_available",
            "tenant_id",
            "available_at",
            "received_at",
            postgresql_where=text("processing_status = 'received'"),
        ),
        Index(
            "ix_integration_event_inbox_expired_lease",
            "tenant_id",
            "lease_until",
            postgresql_where=text("processing_status = 'processing'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_product: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    contract_name: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_version: Mapped[int] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encrypted_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    event_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    event_digest_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="received", server_default="received"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class CRMMarketingCampaign(Base):
    """Tenant- and organization-scoped draft marketing plan linked to a saved segment."""

    __tablename__ = "crm_marketing_campaigns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaigns_tenant_id"),
        UniqueConstraint("tenant_id", "organization_unit_id", "id", name="uq_crm_marketing_campaigns_tenant_org_id"),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_crm_marketing_campaigns_name",
        ),
        CheckConstraint(
            "objective_key ~ '^[a-z][a-z0-9_.-]{0,79}' AND objective_key !~ '[^a-z0-9_.-]'",
            name="ck_crm_marketing_campaigns_objective",
        ),
        CheckConstraint(
            "channel IN ('email', 'phone', 'messaging', 'social', 'web', 'store', 'field', 'other')",
            name="ck_crm_marketing_campaigns_channel",
        ),
        CheckConstraint("status IN ('draft', 'archived')", name="ck_crm_marketing_campaigns_status"),
        CheckConstraint(
            "(planned_budget_amount IS NULL AND planned_budget_currency IS NULL) OR "
            "(planned_budget_amount IS NOT NULL AND planned_budget_amount >= 0 "
            "AND length(planned_budget_currency) = 3 "
            "AND planned_budget_currency = upper(planned_budget_currency) "
            "AND planned_budget_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaigns_budget_pair",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR starts_at < ends_at",
            name="ck_crm_marketing_campaigns_schedule_order",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaigns_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaigns_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "segment_id"],
            ["crm_profile_segments.tenant_id", "crm_profile_segments.id"],
            name="fk_crm_marketing_campaigns_segment_same_tenant", ondelete="RESTRICT",
        ),
        Index(
            "ix_crm_marketing_campaigns_tenant_org_status",
            "tenant_id", "organization_unit_id", "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    segment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    objective_key: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    planned_budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    planned_budget_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )

class CRMMarketingBudgetScenario(Base):
    """Alternative, non-committing marketing budget allocation scenario."""

    __tablename__ = "crm_marketing_budget_scenarios"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_budget_scenarios_tenant_id"),
        UniqueConstraint(
            "tenant_id", "id", "organization_unit_id",
            name="uq_crm_marketing_budget_scenarios_tenant_id_org",
        ),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 160", name="ck_crm_marketing_budget_scenarios_name"),
        CheckConstraint("status IN ('draft', 'archived')", name="ck_crm_marketing_budget_scenarios_status"),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_budget_scenarios_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_budget_scenarios_org_same_tenant", ondelete="RESTRICT",
        ),
        Index("ix_crm_marketing_budget_scenarios_tenant_org_status", "tenant_id", "organization_unit_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"))


class CRMMarketingBudgetScenarioLine(Base):
    """Campaign allocation in one isolated budget scenario."""

    __tablename__ = "crm_marketing_budget_scenario_lines"
    __table_args__ = (
        CheckConstraint(
            "planned_budget_amount >= 0 AND length(planned_budget_currency) = 3 "
            "AND planned_budget_currency = upper(planned_budget_currency) "
            "AND planned_budget_currency ~ '^[A-Z][A-Z][A-Z]'",
            name="ck_crm_marketing_budget_scenario_lines_budget",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "scenario_id", "organization_unit_id"],
            ["crm_marketing_budget_scenarios.tenant_id", "crm_marketing_budget_scenarios.id", "crm_marketing_budget_scenarios.organization_unit_id"],
            name="fk_crm_marketing_budget_scenario_lines_scenario_same_org", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id", "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_budget_scenario_lines_campaign_same_org", ondelete="CASCADE",
        ),
        Index("ix_crm_marketing_budget_scenario_lines_scenario", "tenant_id", "scenario_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    planned_budget_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    planned_budget_currency: Mapped[str] = mapped_column(String(3), nullable=False)


class CRMMarketingCampaignMeasurement(Base):
    """Externally recorded daily metrics for a planned marketing campaign."""

    __tablename__ = "crm_marketing_campaign_measurements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_measurements_tenant_id"),
        UniqueConstraint(
            "tenant_id", "campaign_id", "measured_on",
            name="uq_crm_marketing_campaign_measurements_campaign_day",
        ),
        CheckConstraint(
            "length(trim(source_label)) BETWEEN 1 AND 120",
            name="ck_crm_marketing_campaign_measurements_source",
        ),
        CheckConstraint(
            "(impressions IS NULL OR impressions >= 0) AND "
            "(reach IS NULL OR reach >= 0) AND "
            "(clicks IS NULL OR clicks >= 0) AND "
            "(responses IS NULL OR responses >= 0) AND "
            "(leads IS NULL OR leads >= 0) AND "
            "(conversions IS NULL OR conversions >= 0)",
            name="ck_crm_marketing_campaign_measurements_counts",
        ),
        CheckConstraint(
            "(actual_spend_amount IS NULL AND actual_spend_currency IS NULL) OR "
            "(actual_spend_amount IS NOT NULL AND actual_spend_amount >= 0 "
            "AND length(actual_spend_currency) = 3 "
            "AND actual_spend_currency = upper(actual_spend_currency) "
            "AND actual_spend_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_measurements_spend",
        ),
        CheckConstraint(
            "(attributed_revenue_amount IS NULL AND attributed_revenue_currency IS NULL) OR "
            "(attributed_revenue_amount IS NOT NULL AND attributed_revenue_amount >= 0 "
            "AND length(attributed_revenue_currency) = 3 "
            "AND attributed_revenue_currency = upper(attributed_revenue_currency) "
            "AND attributed_revenue_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_measurements_revenue",
        ),
        CheckConstraint(
            "impressions IS NOT NULL OR reach IS NOT NULL OR clicks IS NOT NULL OR "
            "responses IS NOT NULL OR leads IS NOT NULL OR conversions IS NOT NULL OR "
            "actual_spend_amount IS NOT NULL OR attributed_revenue_amount IS NOT NULL",
            name="ck_crm_marketing_campaign_measurements_has_observation",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_measurements_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_measurements_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_measurements_campaign_same_org", ondelete="CASCADE",
        ),
        Index(
            "ix_crm_marketing_campaign_measurements_tenant_org_day",
            "tenant_id", "organization_unit_id", "measured_on",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    measured_on: Mapped[date] = mapped_column(Date(), nullable=False)
    source_label: Mapped[str] = mapped_column(String(120), nullable=False)
    impressions: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    reach: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    clicks: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    responses: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    leads: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    conversions: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    actual_spend_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    actual_spend_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    attributed_revenue_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    attributed_revenue_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )



class CRMMarketingMeasurementImportBatch(Base):
    """Idempotency receipt for one atomic campaign measurement CSV import."""

    __tablename__ = "crm_marketing_measurement_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id",
            name="uq_crm_marketing_measurement_import_batches_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "campaign_id", "idempotency_key",
            name="uq_crm_marketing_measurement_import_batches_campaign_key",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) BETWEEN 1 AND 80",
            name="ck_crm_marketing_measurement_import_batches_key",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 ~ '^[0-9a-f]{64}'",
            name="ck_crm_marketing_measurement_import_batches_hash",
        ),
        CheckConstraint(
            "row_count BETWEEN 1 AND 366 AND created_count >= 0 AND updated_count >= 0 "
            "AND created_count + updated_count = row_count",
            name="ck_crm_marketing_measurement_import_batches_counts",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_measurement_import_batches_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_measurement_import_batches_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_measurement_import_batches_campaign_same_org", ondelete="CASCADE",
        ),
        Index(
            "ix_crm_marketing_measurement_import_batches_tenant_campaign",
            "tenant_id", "campaign_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
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
            "purpose_key ~ '^[a-z][a-z0-9_.-]{0,79}"+chr(36)+"'",
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



class ProductCustomerIdentity(Base):
    """Stable source-product customer key mapped to one CRM profile per tenant."""

    __tablename__ = "product_customer_identities"
    __table_args__ = (
        CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_product_customer_identities_source",
        ),
        CheckConstraint(
            "length(trim(external_customer_id)) BETWEEN 1 AND 200",
            name="ck_product_customer_identities_external_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_product_customer_identities_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_product_customer_identities_profile_same_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "source_product",
            "profile_id",
            name="uq_product_customer_identities_profile_source",
        ),
        Index(
            "ix_product_customer_identities_tenant_profile",
            "tenant_id",
            "profile_id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_product: Mapped[str] = mapped_column(String(80), primary_key=True)
    external_customer_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )



class CRMOpportunity(Base):
    """Tenant- and organization-scoped sales opportunity in a configurable pipeline."""

    __tablename__ = "crm_opportunities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_opportunities_tenant_id"),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 200",
            name="ck_crm_opportunities_name",
        ),
        CheckConstraint(
            "stage_key ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_opportunities_stage_key",
        ),
        CheckConstraint(
            "(amount IS NULL AND currency IS NULL) OR "
            "(amount IS NOT NULL AND amount >= 0 AND currency IS NOT NULL "
            "AND currency ~ '^[A-Z]{3}$')",
            name="ck_crm_opportunities_amount_currency",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_opportunities_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_opportunities_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_opportunities_profile_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"],
            ["crm_pipelines.tenant_id", "crm_pipelines.id"],
            name="fk_crm_opportunities_pipeline_same_tenant", ondelete="RESTRICT",
        ),
        Index(
            "ix_crm_opportunities_tenant_org_stage",
            "tenant_id", "organization_unit_id", "pipeline_id", "stage_key",
        ),
        Index("ix_crm_opportunities_tenant_profile", "tenant_id", "profile_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    pipeline_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CRMCustomerActivity(Base):
    """Append-only, structured activity from an explicitly connected product."""

    __tablename__ = "crm_customer_activities"
    __table_args__ = (
        CheckConstraint(
            "length(trim(source_product)) BETWEEN 2 AND 80",
            name="ck_crm_customer_activities_source",
        ),
        CheckConstraint(
            "activity_type ~ '^[a-z][a-z0-9_.-]{0,79}$'",
            name="ck_crm_customer_activities_type",
        ),
        CheckConstraint(
            "channel IN ('online', 'phone', 'store', 'field', 'support', 'campaign', 'other')",
            name="ck_crm_customer_activities_channel",
        ),
        CheckConstraint(
            "source_record_id IS NULL OR length(trim(source_record_id)) BETWEEN 1 AND 200",
            name="ck_crm_customer_activities_source_record",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["workspaces.id"],
            name="fk_crm_customer_activities_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_customer_activities_profile_same_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.id"],
            name="fk_crm_customer_activities_campaign_same_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "source_product",
            "source_event_id",
            name="uq_crm_customer_activities_source_event",
        ),
        Index(
            "ix_crm_customer_activities_tenant_profile_time",
            "tenant_id",
            "profile_id",
            "occurred_at",
        ),
        Index(
            "ix_crm_customer_activities_tenant_campaign_time",
            "tenant_id",
            "campaign_id",
            "occurred_at",
            postgresql_where=text("campaign_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_product: Mapped[str] = mapped_column(String(80), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CRMMarketingCampaignTargetPlan(Base):
    """Manager-entered campaign goals for one explicit measurement period."""

    __tablename__ = "crm_marketing_campaign_target_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_target_plans_tenant_id"),
        UniqueConstraint(
            "tenant_id", "campaign_id", "period_start", "period_end",
            name="uq_crm_marketing_campaign_target_plans_campaign_period",
        ),
        CheckConstraint("period_start <= period_end AND period_end - period_start < 366",
                        name="ck_crm_marketing_campaign_target_plans_period"),
        CheckConstraint(
            "(impressions_target IS NULL OR impressions_target >= 0) AND "
            "(clicks_target IS NULL OR clicks_target >= 0) AND "
            "(leads_target IS NULL OR leads_target >= 0) AND "
            "(conversions_target IS NULL OR conversions_target >= 0)",
            name="ck_crm_marketing_campaign_target_plans_counts",
        ),
        CheckConstraint(
            "(max_spend_amount IS NULL AND max_spend_currency IS NULL) OR "
            "(max_spend_amount IS NOT NULL AND max_spend_amount >= 0 AND "
            "length(max_spend_currency) = 3 AND max_spend_currency = upper(max_spend_currency) "
            "AND max_spend_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_spend_pair",
        ),
        CheckConstraint(
            "(max_cpl_amount IS NULL AND cpl_currency IS NULL) OR "
            "(max_cpl_amount IS NOT NULL AND max_cpl_amount >= 0 AND "
            "length(cpl_currency) = 3 AND cpl_currency = upper(cpl_currency) "
            "AND cpl_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_cpl_pair",
        ),
        CheckConstraint(
            "(max_cost_per_conversion_amount IS NULL AND conversion_cost_currency IS NULL) OR "
            "(max_cost_per_conversion_amount IS NOT NULL AND max_cost_per_conversion_amount >= 0 AND "
            "length(conversion_cost_currency) = 3 AND conversion_cost_currency = upper(conversion_cost_currency) "
            "AND conversion_cost_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_conversion_cost_pair",
        ),
        CheckConstraint(
            "(min_roas IS NULL AND roas_currency IS NULL) OR "
            "(min_roas IS NOT NULL AND min_roas >= 0 AND length(roas_currency) = 3 "
            "AND roas_currency = upper(roas_currency) AND roas_currency ~ '^[A-Z][A-Z][A-Z]')",
            name="ck_crm_marketing_campaign_target_plans_roas_pair",
        ),
        CheckConstraint(
            "impressions_target IS NOT NULL OR clicks_target IS NOT NULL OR leads_target IS NOT NULL OR "
            "conversions_target IS NOT NULL OR max_spend_amount IS NOT NULL OR max_cpl_amount IS NOT NULL OR "
            "max_cost_per_conversion_amount IS NOT NULL OR min_roas IS NOT NULL",
            name="ck_crm_marketing_campaign_target_plans_has_goal",
        ),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_target_plans_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_target_plans_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_target_plans_campaign_same_org", ondelete="CASCADE"),
        Index("ix_crm_marketing_campaign_target_plans_tenant_campaign",
              "tenant_id", "campaign_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[date] = mapped_column(Date(), nullable=False)
    impressions_target: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    clicks_target: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    leads_target: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    conversions_target: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    max_spend_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_spend_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    max_cpl_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    cpl_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    max_cost_per_conversion_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    conversion_cost_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    min_roas: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    roas_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class CRMMarketingCampaignExperiment(Base):
    """A manager-defined comparison of campaign variants over a shared period."""

    __tablename__ = "crm_marketing_campaign_experiments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_campaign_experiments_tenant_id"),
        UniqueConstraint(
            "tenant_id", "organization_unit_id", "id",
            name="uq_crm_marketing_campaign_experiments_tenant_org_id",
        ),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160 AND length(trim(hypothesis)) BETWEEN 1 AND 1000",
            name="ck_crm_marketing_campaign_experiments_text",
        ),
        CheckConstraint(
            "period_start <= period_end AND period_end - period_start < 366",
            name="ck_crm_marketing_campaign_experiments_period",
        ),
        CheckConstraint(
            "primary_metric IN ('impressions', 'clicks', 'leads', 'conversions', "
            "'click_through_rate_percent', 'conversion_rate_per_click_percent', "
            "'cost_per_lead', 'cost_per_conversion', 'roas')",
            name="ck_crm_marketing_campaign_experiments_metric",
        ),
        CheckConstraint(
            "(primary_metric IN ('cost_per_lead', 'cost_per_conversion', 'roas') "
            "AND currency IS NOT NULL AND length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z][A-Z][A-Z]') OR "
            "(primary_metric NOT IN ('cost_per_lead', 'cost_per_conversion', 'roas') AND currency IS NULL)",
            name="ck_crm_marketing_campaign_experiments_currency",
        ),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_experiments_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_campaign_experiments_org_same_tenant", ondelete="RESTRICT"),
        Index(
            "ix_crm_marketing_campaign_experiments_tenant_org_period",
            "tenant_id", "organization_unit_id", "period_start", "period_end",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    hypothesis: Mapped[str] = mapped_column(String(1000), nullable=False)
    primary_metric: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[date] = mapped_column(Date(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )


class CRMMarketingCampaignExperimentVariant(Base):
    """Campaign assignment and manager-supplied label for one experiment arm."""

    __tablename__ = "crm_marketing_campaign_experiment_variants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "experiment_id", "campaign_id",
            name="uq_crm_marketing_campaign_experiment_variants_campaign",
        ),
        CheckConstraint("length(trim(label)) BETWEEN 1 AND 80",
                        name="ck_crm_marketing_campaign_experiment_variants_label"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_campaign_experiment_variants_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "experiment_id"],
            ["crm_marketing_campaign_experiments.tenant_id",
             "crm_marketing_campaign_experiments.organization_unit_id",
             "crm_marketing_campaign_experiments.id"],
            name="fk_crm_marketing_campaign_experiment_variants_experiment_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_campaign_experiment_variants_campaign_same_org",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_crm_marketing_campaign_experiment_variants_one_control",
            "tenant_id", "experiment_id", unique=True,
            postgresql_where=text("is_control"),
        ),
        Index(
            "ix_crm_marketing_campaign_experiment_variants_tenant_campaign",
            "tenant_id", "campaign_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    experiment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_control: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class CRMMarketingLearningReview(Base):
    """Manager-authored review linking a target outcome to a corrective action and follow-up."""

    __tablename__ = "crm_marketing_learning_reviews"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_marketing_learning_reviews_tenant_id"),
        CheckConstraint(
            "length(trim(assessment)) BETWEEN 1 AND 1200 "
            "AND length(trim(corrective_action)) BETWEEN 1 AND 1200",
            name="ck_crm_marketing_learning_reviews_required_text",
        ),
        CheckConstraint(
            "status IN ('planned', 'evaluated')",
            name="ck_crm_marketing_learning_reviews_status",
        ),
        CheckConstraint(
            "(status = 'planned' AND follow_up_target_plan_id IS NULL "
            "AND follow_up_effectiveness IS NULL AND lesson_learned IS NULL) OR "
            "(status = 'evaluated' AND follow_up_target_plan_id IS NOT NULL "
            "AND follow_up_effectiveness IS NOT NULL AND length(trim(follow_up_effectiveness)) > 0 "
            "AND lesson_learned IS NOT NULL AND length(trim(lesson_learned)) > 0)",
            name="ck_crm_marketing_learning_reviews_evaluation",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["workspaces.id"],
            name="fk_crm_marketing_learning_reviews_workspace", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_marketing_learning_reviews_org_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_marketing_learning_reviews_campaign_same_org", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_plan_id"],
            ["crm_marketing_campaign_target_plans.tenant_id",
             "crm_marketing_campaign_target_plans.id"],
            name="fk_crm_marketing_learning_reviews_target_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "follow_up_target_plan_id"],
            ["crm_marketing_campaign_target_plans.tenant_id",
             "crm_marketing_campaign_target_plans.id"],
            name="fk_crm_marketing_learning_reviews_followup_same_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "experiment_id"],
            ["crm_marketing_campaign_experiments.tenant_id",
             "crm_marketing_campaign_experiments.organization_unit_id",
             "crm_marketing_campaign_experiments.id"],
            name="fk_crm_marketing_learning_reviews_experiment_same_org", ondelete="RESTRICT",
        ),
        Index(
            "ix_crm_marketing_learning_reviews_tenant_campaign_status",
            "tenant_id", "campaign_id", "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_plan_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    experiment_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    follow_up_target_plan_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    assessment: Mapped[str] = mapped_column(String(1200), nullable=False)
    corrective_action: Mapped[str] = mapped_column(String(1200), nullable=False)
    follow_up_effectiveness: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    lesson_learned: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="planned", server_default="planned"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), server_default=text("now()"),
    )



class CRMCustomerSupportCase(Base):
    """Organization-scoped customer service case with an auditable response deadline."""

    __tablename__ = "crm_support_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_support_cases_tenant_id"),
        CheckConstraint("length(trim(subject)) BETWEEN 1 AND 200",
                        name="ck_crm_support_cases_subject"),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_crm_support_cases_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_customer', 'resolved', 'closed')",
            name="ck_crm_support_cases_status",
        ),
        CheckConstraint(
            "(status IN ('resolved', 'closed') AND resolved_at IS NOT NULL) OR "
            "(status NOT IN ('resolved', 'closed') AND resolved_at IS NULL)",
            name="ck_crm_support_cases_resolution_timestamp",
        ),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_support_cases_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_support_cases_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_support_cases_profile_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "assigned_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_support_cases_assignee_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_support_cases_creator_same_tenant", ondelete="RESTRICT"),
        Index("ix_crm_support_cases_tenant_org_status_due",
              "tenant_id", "organization_unit_id", "status", "response_due_at"),
        Index("ix_crm_support_cases_tenant_assignee_status_due",
              "tenant_id", "assigned_membership_id", "status", "response_due_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assigned_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, server_default="normal")
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))



class CRMCustomerSupportCaseEntry(Base):
    """Append-only staff-authored support case note or recorded response."""

    __tablename__ = "crm_support_case_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_support_case_entries_tenant_id"),
        CheckConstraint(
            "entry_kind IN ('internal_note', 'response_record')",
            name="ck_crm_support_case_entries_kind",
        ),
        CheckConstraint("length(trim(body)) BETWEEN 1 AND 4000",
                        name="ck_crm_support_case_entries_body"),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_support_case_entries_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "support_case_id"],
            ["crm_support_cases.tenant_id", "crm_support_cases.id"],
            name="fk_crm_support_case_entries_case_same_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "author_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_support_case_entries_author_same_tenant", ondelete="RESTRICT"),
        Index("ix_crm_support_case_entries_tenant_case_created",
              "tenant_id", "support_case_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    support_case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    author_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CRMWorkItem(Base):
    """A tenant-scoped future action for a customer, opportunity, or campaign."""

    __tablename__ = "crm_work_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_crm_work_items_tenant_id"),
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 200",
                        name="ck_crm_work_items_title"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')",
                        name="ck_crm_work_items_priority"),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'completed', 'cancelled')",
            name="ck_crm_work_items_status",
        ),
        CheckConstraint(
            "profile_id IS NOT NULL OR opportunity_id IS NOT NULL OR campaign_id IS NOT NULL",
            name="ck_crm_work_items_has_context",
        ),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name="ck_crm_work_items_completion_timestamp",
        ),
        ForeignKeyConstraint(["tenant_id"], ["workspaces.id"],
            name="fk_crm_work_items_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "organization_unit_id"],
            ["organization_units.tenant_id", "organization_units.id"],
            name="fk_crm_work_items_org_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "profile_id"],
            ["crm_profiles.tenant_id", "crm_profiles.id"],
            name="fk_crm_work_items_profile_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "opportunity_id"],
            ["crm_opportunities.tenant_id", "crm_opportunities.id"],
            name="fk_crm_work_items_opportunity_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_unit_id", "campaign_id"],
            ["crm_marketing_campaigns.tenant_id", "crm_marketing_campaigns.organization_unit_id",
             "crm_marketing_campaigns.id"],
            name="fk_crm_work_items_campaign_same_org", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "assigned_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_items_assignee_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "created_by_membership_id"],
            ["workspace_memberships.tenant_id", "workspace_memberships.id"],
            name="fk_crm_work_items_creator_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "source_learning_review_id"],
            ["crm_marketing_learning_reviews.tenant_id", "crm_marketing_learning_reviews.id"],
            name="fk_crm_work_items_learning_review_same_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "source_outcome_id"],
            ["crm_work_item_outcomes.tenant_id", "crm_work_item_outcomes.id"],
            name="fk_crm_work_items_outcome_same_tenant", ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "source_learning_review_id",
                         name="uq_crm_work_items_source_learning_review"),
        UniqueConstraint("tenant_id", "source_outcome_id",
                         name="uq_crm_work_items_source_outcome"),
        Index(
            "ix_crm_work_items_tenant_org_status_due",
            "tenant_id", "organization_unit_id", "status", "due_at",
        ),
        Index(
            "ix_crm_work_items_tenant_assignee_status_due",
            "tenant_id", "assigned_membership_id", "status", "due_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_unit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    campaign_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    assigned_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_learning_review_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
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
