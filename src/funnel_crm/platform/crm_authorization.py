"""Database-backed CRM permission evaluation for explicit organization scopes."""

from uuid import UUID

from sqlalchemy import false, select
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
        "crm.custom_field:view",
        "crm.custom_field:update",
        "crm.profile:view",
        "crm.profile:create",
        "crm.profile:update",
        "crm.profile:archive",
        "crm.profile:export",
        "crm.contact_point:view",
        "crm.contact_point:create",
        "crm.contact_point:update",
        "crm.communication_consent:view",
        "crm.communication_consent:record",
        "crm.profile:review_duplicates",
        "crm.segment:view",
        "crm.segment:manage",
        "crm.integration:manage",
    }
)


def crm_scope_ids(
    context: TenantSessionContext,
    *,
    permission_key: str,
    cte_name: str = "crm_assigned_scope",
):
    """Build a tenant-bound query of units covered by one CRM permission.

    Role grant, membership, and assigned scope are joined before descendants are
    expanded. UNION deduplicates nodes so malformed cyclic trees cannot recurse
    forever. Unknown permissions return an empty scope.
    """
    if permission_key not in CRM_PERMISSION_KEYS:
        return select(OrganizationUnit.id).where(false())

    tenant_id = context.access.tenant_id
    assigned_units = (
        select(
            OrganizationUnit.id.label("id"),
        )
        .join(
            RoleAssignment,
            (RoleAssignment.tenant_id == OrganizationUnit.tenant_id)
            & (RoleAssignment.organization_unit_id == OrganizationUnit.id),
        )
        .join(
            WorkspaceMembership,
            (WorkspaceMembership.tenant_id == RoleAssignment.tenant_id)
            & (WorkspaceMembership.id == RoleAssignment.membership_id),
        )
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
            OrganizationUnit.tenant_id == tenant_id,
            RoleAssignment.tenant_id == tenant_id,
            RoleAssignment.membership_id == context.access.membership_id,
            WorkspaceMembership.status == "active",
            Role.is_active.is_(True),
            RolePermission.permission_key == permission_key,
        )
        .cte(cte_name, recursive=True)
    )
    child_unit = aliased(OrganizationUnit)
    expanded_scope = assigned_units.union(
        select(child_unit.id)
        .join(assigned_units, child_unit.parent_id == assigned_units.c.id)
        .where(child_unit.tenant_id == tenant_id)
    )
    return select(expanded_scope.c.id).distinct()


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
    return (
        await context.session.scalar(
            select(OrganizationUnit.id)
            .where(
                OrganizationUnit.tenant_id == tenant_id,
                OrganizationUnit.id == organization_unit_id,
                OrganizationUnit.id.in_(
                    crm_scope_ids(context, permission_key=permission_key)
                ),
            )
            .limit(1)
        )
        is not None
    )
