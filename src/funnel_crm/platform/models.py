"""Persistence models for tenant workspaces and organization units."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
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
