from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.platform.models import OrganizationUnit, Workspace
from funnel_crm.platform.tenant_context import (
    AuthenticatedIdentity,
    WorkspaceAccessDenied,
    tenant_session,
)


@pytest.mark.asyncio
async def test_rls_filters_reads_and_rejects_cross_tenant_writes(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    workspace_a = tenant_case["workspace_a"]
    workspace_b = tenant_case["workspace_b"]
    identity = tenant_case["identity"]
    assert isinstance(workspace_a, UUID)
    assert isinstance(workspace_b, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=workspace_a,
        identity=identity,
    ) as context:
        visible_ids = set((await context.session.scalars(select(Workspace.id))).all())
        assert visible_ids == {workspace_a}

        foreign_org = await context.session.get(
            OrganizationUnit, tenant_case["root_b"]
        )
        assert foreign_org is None

        async with context.session.begin_nested():
            context.session.add(
                Workspace(
                    id=workspace_b,
                    display_name="cross-tenant write",
                    root_organization_id=tenant_case["root_b"],
                    root_organization_type="root",
                )
            )
            with pytest.raises(DBAPIError):
                await context.session.flush()


@pytest.mark.asyncio
async def test_transaction_local_tenant_context_does_not_leak_through_pool(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    workspace_a = tenant_case["workspace_a"]
    workspace_b = tenant_case["workspace_b"]
    identity = tenant_case["identity"]
    identity_b = tenant_case["identity_b"]
    assert isinstance(workspace_a, UUID)
    assert isinstance(workspace_b, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    assert isinstance(identity_b, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=workspace_a,
        identity=identity,
    ):
        pass

    # Pool size is one in the fixture, so this inspects the same physical
    # connection after the first transaction has returned it to the pool.
    async with runtime_session_factory() as session:
        async with session.begin():
            tenant_setting = await session.scalar(
                text("SELECT NULLIF(current_setting('app.tenant_id', true), '')")
            )
            assert tenant_setting is None
            assert (await session.scalars(select(Workspace.id))).all() == []

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=workspace_b,
        identity=identity_b,
    ) as context:
        visible_ids = set((await context.session.scalars(select(Workspace.id))).all())
        assert visible_ids == {workspace_b}


@pytest.mark.asyncio
async def test_requested_workspace_without_active_membership_is_denied(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    workspace_b = tenant_case["workspace_b"]
    identity = tenant_case["identity"]
    assert isinstance(workspace_b, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    with pytest.raises(WorkspaceAccessDenied):
        async with tenant_session(
            runtime_session_factory,
            requested_tenant_id=workspace_b,
            identity=identity,
        ):
            pytest.fail("inactive or absent membership must never yield a tenant session")
