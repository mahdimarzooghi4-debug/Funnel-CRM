"""Persistence models for tenant workspaces and organization units."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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
