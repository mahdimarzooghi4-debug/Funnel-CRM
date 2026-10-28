from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_marketing_calendar import router
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMProfileSegment,
    CRMWorkItem,
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
async def test_marketing_calendar_combines_scoped_campaigns_and_work_items(
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
            name=f"Calendar audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        role = Role(tenant_id=tenant_id, name=f"Calendar manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:view"),
        ])
        context.session.add(CRMMarketingCampaign(
            id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="October launch", objective_key="acquisition",
            channel="store", planned_budget_amount=None, planned_budget_currency=None,
            starts_at=datetime(2026, 10, 20, 9, tzinfo=timezone.utc),
            ends_at=datetime(2026, 10, 22, 18, tzinfo=timezone.utc), status="draft",
        ))
        context.session.add(CRMWorkItem(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            profile_id=None, opportunity_id=None, campaign_id=campaign_id,
            assigned_membership_id=context.access.membership_id,
            created_by_membership_id=context.access.membership_id,
            title="Prepare store launch materials", description=None,
            due_at=datetime(2026, 10, 21, 12, tzinfo=timezone.utc),
            priority="high", status="open", completed_at=None,
            source_learning_review_id=None, source_outcome_id=None,
        ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-Workspace-ID": str(tenant_id)}
        response = await client.get(
            "/api/v1/crm/marketing-calendar/events",
            headers=headers,
            params={"period_start": "2026-10-20", "period_end": "2026-10-22"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["visible_sources"] == ["campaigns", "work_items"]
        assert [(item["kind"], item["title"]) for item in result["events"]] == [
            ("campaign", "October launch"),
            ("work_item", "Prepare store launch materials"),
        ]
        assert result["events"][0]["channel"] == "store"
        assert result["events"][0]["end_date"] == "2026-10-22"
        assert result["events"][1]["priority"] == "high"
        assert result["events"][1]["campaign_id"] == str(campaign_id)
        assert result["has_more"] is False

        invalid_range = await client.get(
            "/api/v1/crm/marketing-calendar/events",
            headers=headers,
            params={"period_start": "2026-01-01", "period_end": "2026-04-10"},
        )
        assert invalid_range.status_code == 422
