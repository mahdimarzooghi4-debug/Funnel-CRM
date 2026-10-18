from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaigns import router
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    identity: AuthenticatedIdentity,
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_campaign_planning_lifecycle_is_scoped_and_never_sends(
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
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        segment = CRMProfileSegment(
            id=uuid4(),
            tenant_id=tenant_id,
            organization_unit_id=root_id,
            name=f"Campaign audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]},
            is_active=True,
        )
        context.session.add(segment)
        role = Role(tenant_id=tenant_id, name=f"Campaign manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(
            [
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=role.id,
                    organization_unit_id=root_id,
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.campaign:view",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.campaign:manage",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.segment:view",
                ),
            ]
        )
        await context.session.flush()
        segment_id = segment.id

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        starts = datetime.now(timezone.utc) + timedelta(days=3)
        ends = starts + timedelta(days=7)
        created = await client.post(
            "/api/v1/crm/campaigns",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "segment_id": str(segment_id),
                "name": "Spring offer",
                "objective_key": "repeat_purchase",
                "channel": "email",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        listed = await client.get("/api/v1/crm/campaigns", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == campaign_id

        updated = await client.patch(
            f"/api/v1/crm/campaigns/{campaign_id}",
            headers=headers,
            json={"channel": "store", "ends_at": (ends + timedelta(days=1)).isoformat()},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["channel"] == "store"

        archived = await client.post(
            f"/api/v1/crm/campaigns/{campaign_id}/archive", headers=headers
        )
        assert archived.status_code == 204

        archived_list = await client.get(
            "/api/v1/crm/campaigns?status=archived", headers=headers
        )
        assert archived_list.status_code == 200
        assert archived_list.json()["total"] == 1

        cannot_edit = await client.patch(
            f"/api/v1/crm/campaigns/{campaign_id}",
            headers=headers,
            json={"name": "Changed after archive"},
        )
        assert cannot_edit.status_code == 409

        no_sender = await client.post(
            f"/api/v1/crm/campaigns/{campaign_id}/send", headers=headers
        )
        assert no_sender.status_code == 404

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        stored = await context.session.scalar(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.id == UUID(campaign_id),
            )
        )
        assert stored is not None
        assert stored.status == "archived"
        assert stored.channel == "store"
