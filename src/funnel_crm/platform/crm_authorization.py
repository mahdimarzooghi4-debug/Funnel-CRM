"""Database-backed CRM permission evaluation for an explicit organization scope."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import aliased

from funnel_crm.platform.models import (
    OrganizationUnit,
    Role,
    RoleAssignment,
    RolePermission,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import TenantSessionContext


CRM_PERMISSION_KEYS = frozenset(
    {
        "crm.settings:manage",
        "crm.pipeline:manage",
        "crm.custom_field:manage",
        "crm.profile:view",
        "crm.profile:create",
        "crm.profile:update",
        "crm.profile:archive",
        "crm.profile:export",
    }
)


async def has_crm_permission(
    context: TenantSessionContext,
    *,
    permission_key: str,
    organization_unit_id: UUID,
) -> bool:
    """Return whether this active member has an action grant in the given scope.

    Assignments apply to their organization unit and descendants. The role grant
    and organization scope must come from the same assignment. Unknown keys and
    units outside the verified workspace are denied.
    """
    if permission_key not in CRM_PERMISSION_KEYS:
        return False

    tenant_id = context.access.tenant_id
    membership_status = await context.session.scalar(
        select(WorkspaceMembership.status).where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.id == context.access.membership_id,
        )
    )
    if membership_status != "active":
        return False

    scope_path = (
        select(
            OrganizationUnit.id.label("id"),
            OrganizationUnit.parent_id.label("parent_id"),
        )
        .where(
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.id == organization_unit_id,
        )
        .cte("crm_authorization_scope", recursive=True)
    )
    parent_unit = aliased(OrganizationUnit)
    scope_path = scope_path.union_all(
        select(parent_unit.id, parent_unit.parent_id)
        .join(scope_path, parent_unit.id == scope_path.c.parent_id)
        .where(parent_unit.tenant_id == tenant_id)
    )

    matching_assignment = (
        select(RoleAssignment.id)
        .join(
            Role,
            (Role.tenant_id == RoleAssignment.tenant_id)
            & (Role.id == RoleAssignment.role_id),
        )
        .join(
            RolePermission,
            (RolePermission.tenant_id == RoleAssignment.tenant_id)
            & (RolePermission.role_id == RoleAssignment.role_id),
        )
        .where(
            RoleAssignment.tenant_id == tenant_id,
            RoleAssignment.membership_id == context.access.membership_id,
            RoleAssignment.organization_unit_id.in_(
                select(scope_path.c.id)
            ),
            Role.is_active.is_(True),
            RolePermission.permission_key == permission_key,
        )
        .limit(1)
    )
    return await context.session.scalar(matching_assignment) is not None
