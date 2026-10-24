from uuid import uuid4

from funnel_crm.platform.authorization import (
    MembershipContext,
    RoleScope,
    is_authorized,
)


def test_permission_and_matching_organization_scope_are_both_required() -> None:
    tenant = uuid4()
    role = uuid4()
    assigned_unit = uuid4()
    resource_unit = uuid4()
    membership = MembershipContext(tenant_id=tenant, status="active")
    assignment = RoleScope(tenant, role, assigned_unit)
    grants = {role: frozenset({"campaign:publish"})}

    assert is_authorized(
        membership=membership,
        permission_key="campaign:publish",
        assignments=(assignment,),
        role_permissions=grants,
        resource_organization_path=frozenset({resource_unit, assigned_unit}),
    )
    assert not is_authorized(
        membership=membership,
        permission_key="campaign:delete",
        assignments=(assignment,),
        role_permissions=grants,
        resource_organization_path=frozenset({resource_unit, assigned_unit}),
    )
    assert not is_authorized(
        membership=membership,
        permission_key="campaign:publish",
        assignments=(assignment,),
        role_permissions=grants,
        resource_organization_path=frozenset({resource_unit}),
    )


def test_role_permission_and_scope_cannot_be_combined_across_assignments() -> None:
    tenant = uuid4()
    role_with_permission = uuid4()
    role_with_scope = uuid4()
    assigned_unit = uuid4()
    other_unit = uuid4()
    membership = MembershipContext(tenant_id=tenant, status="active")

    assert not is_authorized(
        membership=membership,
        permission_key="customer:export",
        assignments=(
            RoleScope(tenant, role_with_permission, other_unit),
            RoleScope(tenant, role_with_scope, assigned_unit),
        ),
        role_permissions={role_with_permission: frozenset({"customer:export"})},
        resource_organization_path=frozenset({assigned_unit}),
    )


def test_inactive_membership_role_or_unknown_permission_denies() -> None:
    tenant = uuid4()
    role = uuid4()
    unit = uuid4()
    assignment = RoleScope(tenant, role, unit)
    grants = {role: frozenset({"customer:view"})}

    assert not is_authorized(
        membership=MembershipContext(tenant, "suspended"),
        permission_key="customer:view",
        assignments=(assignment,),
        role_permissions=grants,
        resource_organization_path=frozenset({unit}),
    )
    assert not is_authorized(
        membership=MembershipContext(tenant, "active"),
        permission_key="undefined:action",
        assignments=(assignment,),
        role_permissions=grants,
        resource_organization_path=frozenset({unit}),
    )
    assert not is_authorized(
        membership=MembershipContext(tenant, "active"),
        permission_key="customer:view",
        assignments=(RoleScope(tenant, role, unit, role_active=False),),
        role_permissions=grants,
        resource_organization_path=frozenset({unit}),
    )


def test_assignment_from_a_different_tenant_denies() -> None:
    tenant = uuid4()
    other_tenant = uuid4()
    role = uuid4()
    unit = uuid4()

    assert not is_authorized(
        membership=MembershipContext(tenant, "active"),
        permission_key="customer:view",
        assignments=(RoleScope(other_tenant, role, unit),),
        role_permissions={role: frozenset({"customer:view"})},
        resource_organization_path=frozenset({unit}),
    )
