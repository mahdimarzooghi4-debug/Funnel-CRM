from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from funnel_crm.platform.models import (
    Role,
    RoleAssignment,
    UserIdentity,
    WorkspaceMembership,
)
from funnel_crm.platform.workspaces import create_workspace


@pytest.mark.asyncio
async def test_one_external_identity_can_join_separate_workspaces(
    db_session: AsyncSession,
) -> None:
    first = await create_workspace(db_session, display_name="Workspace A")
    second = await create_workspace(db_session, display_name="Workspace B")
    identity = UserIdentity(issuer="https://identity.example", subject="user-123")
    db_session.add(identity)
    await db_session.flush()
    first_membership = WorkspaceMembership(
        tenant_id=first.id, identity_id=identity.id, status="active"
    )
    second_membership = WorkspaceMembership(
        tenant_id=second.id, identity_id=identity.id, status="invited"
    )
    db_session.add_all([first_membership, second_membership])
    await db_session.flush()

    assert first_membership.tenant_id != second_membership.tenant_id
    assert first_membership.identity_id == second_membership.identity_id


@pytest.mark.asyncio
async def test_role_assignment_cannot_cross_workspace_role_boundary(
    db_session: AsyncSession,
) -> None:
    first = await create_workspace(db_session, display_name="Workspace A")
    second = await create_workspace(db_session, display_name="Workspace B")
    identity = UserIdentity(issuer="https://identity.example", subject="user-456")
    db_session.add(identity)
    await db_session.flush()
    membership = WorkspaceMembership(
        tenant_id=first.id, identity_id=identity.id, status="active"
    )
    foreign_role = Role(tenant_id=second.id, name="Foreign role")
    db_session.add_all([membership, foreign_role])
    await db_session.flush()
    db_session.add(
        RoleAssignment(
            tenant_id=first.id,
            membership_id=membership.id,
            role_id=foreign_role.id,
            organization_unit_id=first.root_organization_id,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_role_assignment_cannot_target_another_workspaces_scope(
    db_session: AsyncSession,
) -> None:
    first = await create_workspace(db_session, display_name="Workspace A")
    second = await create_workspace(db_session, display_name="Workspace B")
    identity = UserIdentity(issuer="https://identity.example", subject="user-789")
    db_session.add(identity)
    await db_session.flush()
    membership = WorkspaceMembership(
        tenant_id=first.id, identity_id=identity.id, status="active"
    )
    role = Role(tenant_id=first.id, name="Local role")
    db_session.add_all([membership, role])
    await db_session.flush()
    db_session.add(
        RoleAssignment(
            tenant_id=first.id,
            membership_id=membership.id,
            role_id=role.id,
            organization_unit_id=second.root_organization_id,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
