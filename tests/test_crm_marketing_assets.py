from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_marketing_assets import router
from funnel_crm.api.v1.crm_campaign_readiness import router as readiness_router
from funnel_crm.platform.models import CRMMarketingCampaign, CRMProfileSegment, Role, RoleAssignment, RolePermission
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
    app.include_router(readiness_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_campaign_asset_review_lifecycle_is_scoped_and_audited(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id, campaign_id = uuid4(), uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Asset audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        role = Role(tenant_id=tenant_id, name=f"Asset manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:manage"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:view"),
        ])
        context.session.add(CRMMarketingCampaign(
            id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Social launch", objective_key="acquisition",
            channel="social", planned_budget_amount=None, planned_budget_currency=None,
            starts_at=datetime(2026, 11, 2, 9, tzinfo=timezone.utc),
            ends_at=datetime(2026, 11, 6, 18, tzinfo=timezone.utc), status="draft",
        ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        invalid_empty = await client.post(
            "/api/v1/crm/marketing-assets",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "campaign_id": str(campaign_id),
                "channel": "social",
                "asset_kind": "copy",
                "title": "Empty asset",
            },
        )
        assert invalid_empty.status_code == 422

        created = await client.post(
            "/api/v1/crm/marketing-assets",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "channel": "social",
                "asset_kind": "copy",
                "title": "Launch post",
                "body": "A draft launch announcement.",
                "locale": "fa-IR",
            },
        )
        assert created.status_code == 201, created.text
        asset_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        submitted = await client.post(
            f"/api/v1/crm/marketing-assets/{asset_id}/submit",
            headers=headers,
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "in_review"
        readiness_pending = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/readiness", headers=headers
        )
        assert readiness_pending.status_code == 200, readiness_pending.text
        assert readiness_pending.json()["launch_readiness"] == "needs_attention"
        pending_check = next(item for item in readiness_pending.json()["checks"] if item["key"] == "approved_content")
        assert pending_check["status"] == "pending"
        assert readiness_pending.json()["open_work_item_count"] == 0

        rejected_without_note = await client.post(
            f"/api/v1/crm/marketing-assets/{asset_id}/review",
            headers=headers,
            json={"decision": "reject"},
        )
        assert rejected_without_note.status_code == 422

        rejected = await client.post(
            f"/api/v1/crm/marketing-assets/{asset_id}/review",
            headers=headers,
            json={"decision": "reject", "note": "Add the campaign date to the copy."},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["review_note"] == "Add the campaign date to the copy."

        revised = await client.patch(
            f"/api/v1/crm/marketing-assets/{asset_id}",
            headers=headers,
            json={"body": "The launch begins on Friday."},
        )
        assert revised.status_code == 200, revised.text
        assert revised.json()["status"] == "draft"
        assert revised.json()["reviewed_at"] is None

        await client.post(f"/api/v1/crm/marketing-assets/{asset_id}/submit", headers=headers)
        approved = await client.post(
            f"/api/v1/crm/marketing-assets/{asset_id}/review",
            headers=headers,
            json={"decision": "approve"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["reviewed_by_membership_id"] is not None
        readiness_approved = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/readiness", headers=headers
        )
        assert readiness_approved.status_code == 200, readiness_approved.text
        assert readiness_approved.json()["launch_readiness"] == "ready_for_manager_review"
        assert readiness_approved.json()["asset_counts"]["approved"] == 1
        assert all(item["status"] == "complete" for item in readiness_approved.json()["checks"])

        immutable = await client.patch(
            f"/api/v1/crm/marketing-assets/{asset_id}",
            headers=headers,
            json={"title": "Replace approved content"},
        )
        assert immutable.status_code == 409

        listed = await client.get(
            "/api/v1/crm/marketing-assets",
            headers=headers,
            params={"organization_unit_id": str(root_id), "status": "approved"},
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == asset_id
