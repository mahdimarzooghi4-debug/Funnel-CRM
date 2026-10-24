from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.platform.crm_authorization import (
    CRM_PERMISSION_KEYS,
    has_crm_permission,
)
from funnel_crm.platform.models import (
    OrganizationUnit,
    PermissionDefinition,
    Role,
    RoleAssignment,
    RolePermission,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


@pytest.mark.asyncio
async def test_crm_permission_requires_matching_action_and_inherited_org_scope(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    unit_a_id, child_a_id, unit_b_id = uuid4(), uuid4(), uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        unit_a = OrganizationUnit(
            id=unit_a_id,
            tenant_id=tenant_id,
            parent_id=root_id,
            name="Branch A",
            unit_type="unit",
        )
        child_a = OrganizationUnit(
            id=child_a_id,
            tenant_id=tenant_id,
            parent_id=unit_a_id,
            name="Team A1",
            unit_type="unit",
        )
        unit_b = OrganizationUnit(
            id=unit_b_id,
            tenant_id=tenant_id,
            parent_id=root_id,
            name="Branch B",
            unit_type="unit",
        )
        context.session.add_all([unit_a, child_a, unit_b])
        await context.session.flush()

        branch_role = Role(tenant_id=tenant_id, name="Branch customer viewer")
        other_branch_role = Role(tenant_id=tenant_id, name="Other branch exporter")
        context.session.add_all([branch_role, other_branch_role])
        await context.session.flush()

        context.session.add_all(
            [
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=branch_role.id,
                    permission_key="crm.profile:view",
                ),
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=other_branch_role.id,
                    permission_key="crm.profile:export",
                ),
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=branch_role.id,
                    organization_unit_id=unit_a_id,
                ),
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=other_branch_role.id,
                    organization_unit_id=unit_b_id,
                ),
            ]
        )
        await context.session.flush()

        assert await has_crm_permission(
            context,
            permission_key="crm.profile:view",
            organization_unit_id=child_a_id,
        )
        assert not await has_crm_permission(
            context,
            permission_key="crm.profile:export",
            organization_unit_id=child_a_id,
        )
        assert not await has_crm_permission(
            context,
            permission_key="crm.profile:view",
            organization_unit_id=unit_b_id,
        )
        assert await has_crm_permission(
            context,
            permission_key="crm.profile:export",
            organization_unit_id=unit_b_id,
        )
        assert not await has_crm_permission(
            context,
            permission_key="crm.profile:delete",
            organization_unit_id=child_a_id,
        )
        assert CRM_PERMISSION_KEYS == frozenset(
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
                "crm.campaign:view",
                "crm.campaign:manage",
                "crm.commerce_event:view",
                "crm.budget_scenario:view",
                "crm.budget_scenario:manage",
                "crm.opportunity:view",
                "crm.opportunity:create",
                "crm.opportunity:update",
                "crm.work_item:view",
                "crm.work_item:create",
                "crm.work_item:update",
                "crm.support_case:view",
                "crm.support_case:create",
                "crm.support_case:update",
            }
        )

        await context.session.execute(
            delete(OrganizationUnit).where(
                OrganizationUnit.tenant_id == tenant_id,
                OrganizationUnit.id == child_a_id,
            )
        )
        await context.session.execute(
            delete(OrganizationUnit).where(
                OrganizationUnit.tenant_id == tenant_id,
                OrganizationUnit.id.in_([unit_a_id, unit_b_id]),
            )
        )


@pytest.mark.asyncio
async def test_crm_permission_catalog_is_seeded_and_inactive_membership_denies(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        catalog = (
            await context.session.scalars(
                select(PermissionDefinition.key).where(
                    PermissionDefinition.key.in_(CRM_PERMISSION_KEYS)
                )
            )
        ).all()
        assert set(catalog) == CRM_PERMISSION_KEYS

        role = Role(tenant_id=tenant_id, name="Workspace profile viewer")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(
            [
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.profile:view",
                ),
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=role.id,
                    organization_unit_id=root_id,
                ),
            ]
        )
        await context.session.flush()
        assert await has_crm_permission(
            context,
            permission_key="crm.profile:view",
            organization_unit_id=root_id,
        )

        membership = await context.session.get(
            WorkspaceMembership, context.access.membership_id
        )
        assert membership is not None
        membership.status = "suspended"
        await context.session.flush()
        assert not await has_crm_permission(
            context,
            permission_key="crm.profile:view",
            organization_unit_id=root_id,
        )
