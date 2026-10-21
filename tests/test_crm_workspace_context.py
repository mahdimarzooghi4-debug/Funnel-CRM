from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_workspace_context import router
from funnel_crm.platform.models import Workspace, WorkspaceMembership, UserIdentity
from funnel_crm.platform.tenant_context import AuthenticatedIdentity


def test_workspace_discovery_requires_verified_identity() -> None:
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/system/workspaces")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_identity_workspace_discovery_is_filtered_by_rls(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    identity = tenant_case["identity"]
    expected_workspace = tenant_case["workspace_a"]
    assert isinstance(identity, AuthenticatedIdentity)
    assert isinstance(expected_workspace, UUID)

    async with runtime_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "SELECT set_config('app.authenticated_issuer', :issuer, true), "
                    "set_config('app.authenticated_subject', :subject, true)"
                ),
                {"issuer": identity.issuer, "subject": identity.subject},
            )
            visible = (
                await session.scalars(
                    select(Workspace.id)
                    .join(WorkspaceMembership, WorkspaceMembership.tenant_id == Workspace.id)
                    .join(UserIdentity, UserIdentity.id == WorkspaceMembership.identity_id)
                    .where(WorkspaceMembership.status == "active")
                )
            ).all()
            assert set(visible) == {expected_workspace}

    # Without transaction-local identity claims neither discovery policy reveals rows.
    async with runtime_session_factory() as session:
        async with session.begin():
            assert (await session.scalars(select(Workspace.id))).all() == []
