"""Deny-by-default authorization for role permission plus organization scope."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MembershipContext:
    tenant_id: UUID
    status: str


@dataclass(frozen=True)
class RoleScope:
    tenant_id: UUID
    role_id: UUID
    organization_unit_id: UUID
    role_active: bool = True


def is_authorized(
    *,
    membership: MembershipContext,
    permission_key: str,
    assignments: tuple[RoleScope, ...],
    role_permissions: dict[UUID, frozenset[str]],
    resource_organization_path: frozenset[UUID],
) -> bool:
    """Evaluate one action against one explicit role-and-scope assignment.

    resource_organization_path must be loaded from the current tenant's
    organization tree and include the resource's unit and its ancestors.
    Keeping role and scope checks on the same assignment prevents combining an
    action from one role with a broader scope from another.
    """
    if membership.status != "active" or not permission_key:
        return False

    for assignment in assignments:
        if assignment.tenant_id != membership.tenant_id or not assignment.role_active:
            continue
        if assignment.organization_unit_id not in resource_organization_path:
            continue
        if permission_key in role_permissions.get(assignment.role_id, frozenset()):
            return True

    return False
