from datetime import date
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_work_items import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory: async_sessionmaker[AsyncSession], identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_work_queue_assigns_campaign_follow_up_and_enforces_lifecycle(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    campaign_id = uuid4()

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        segment = CRMProfileSegment(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Work queue audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        )
        context.session.add(segment)
        await context.session.flush()
        context.session.add(CRMMarketingCampaign(
            id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment.id, name="Store follow-up", objective_key="retention",
            channel="store", planned_budget_amount=None, planned_budget_currency=None,
            starts_at=None, ends_at=None, status="draft",
        ))
        role = Role(tenant_id=tenant_id, name=f"Work queue manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:create"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:update"),
        ])
        await context.session.flush()
        membership_id = context.access.membership_id

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = "/api/v1/crm/work-items"
        missing_context = await client.post(base, headers=headers, json={
            "organization_unit_id": str(root_id),
            "title": "Call the store manager",
        })
        assert missing_context.status_code == 422

        created = await client.post(base, headers=headers, json={
            "organization_unit_id": str(root_id),
            "campaign_id": str(campaign_id),
            "assigned_membership_id": str(membership_id),
            "title": "Call the store manager",
            "description": "Confirm campaign display and stock availability.",
            "due_at": "2026-10-20T12:00:00Z",
            "priority": "high",
        })
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]
        assert created.json()["status"] == "open"
        assert created.json()["priority"] == "high"

        listing = await client.get(base, headers=headers, params={
            "organization_unit_id": str(root_id),
            "assigned_to_me": "true",
        })
        assert listing.status_code == 200, listing.text
        assert [row["id"] for row in listing.json()] == [item_id]

        invalid_reference = await client.post(base, headers=headers, json={
            "organization_unit_id": str(root_id),
            "campaign_id": str(uuid4()),
            "title": "Invalid campaign follow-up",
        })
        assert invalid_reference.status_code == 422

        in_progress = await client.patch(f"{base}/{item_id}", headers=headers, json={
            "status": "in_progress",
        })
        assert in_progress.status_code == 200, in_progress.text
        assert in_progress.json()["status"] == "in_progress"

        completed = await client.patch(f"{base}/{item_id}", headers=headers, json={
            "status": "completed",
        })
        assert completed.status_code == 200, completed.text
        assert completed.json()["completed_at"] is not None

        terminal = await client.patch(f"{base}/{item_id}", headers=headers, json={
            "title": "Try to change a completed item",
        })
        assert terminal.status_code == 409

        detail = await client.get(f"{base}/{item_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["created_by_membership_id"] == str(membership_id)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        events = (await context.session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.target_type == "crm_work_item",
            )
        )).all()
        assert {event.action_key for event in events} >= {
            "crm_work_item.created", "crm_work_item.updated", "crm_work_item.viewed",
            "crm_work_item.listed",
        }


@pytest.mark.asyncio
async def test_work_queue_requires_timezone_and_valid_active_assignee(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        naive_due_date = await client.post("/api/v1/crm/work-items", headers=headers, json={
            "organization_unit_id": str(root_id),
            "campaign_id": str(uuid4()),
            "title": "Follow up",
            "due_at": "2026-10-20T12:00:00",
        })
    assert naive_due_date.status_code == 422
