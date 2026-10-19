from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_sales_operations import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMOpportunity,
    CRMPipeline,
    CRMWorkItem,
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
async def test_sales_operations_dashboard_combines_pipeline_and_follow_up_health(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    pipeline_id, usd_id, eur_id, unpriced_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMPipeline(
            id=pipeline_id, tenant_id=tenant_id,
            pipeline_key=f"dashboard-{uuid4().hex[:8]}",
            entity_kind="opportunity", display_name="Sales dashboard",
            stages=[
                {"key": "qualified", "name": "Qualified", "position": 1, "probability_percent": 60},
                {"key": "proposal", "name": "Proposal", "position": 2, "probability_percent": None},
            ],
            is_default=False,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMOpportunity(
                id=usd_id, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_id=None, pipeline_id=pipeline_id, name="USD deal",
                stage_key="qualified", amount=Decimal("1000"), currency="USD",
                expected_close_date=date(2026, 11, 15),
            ),
            CRMOpportunity(
                id=eur_id, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_id=None, pipeline_id=pipeline_id, name="EUR deal",
                stage_key="proposal", amount=Decimal("500"), currency="EUR",
                expected_close_date=date(2026, 11, 20),
            ),
            CRMOpportunity(
                id=unpriced_id, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_id=None, pipeline_id=pipeline_id, name="Unpriced deal",
                stage_key="qualified", amount=None, currency=None,
                expected_close_date=None,
            ),
        ])
        await context.session.flush()
        now = datetime.now(timezone.utc)
        context.session.add_all([
            CRMWorkItem(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                opportunity_id=usd_id, campaign_id=None, profile_id=None,
                assigned_membership_id=context.access.membership_id,
                created_by_membership_id=context.access.membership_id,
                title="Overdue call", description=None, due_at=now - timedelta(hours=1),
                priority="high", status="open", completed_at=None,
            ),
            CRMWorkItem(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                opportunity_id=usd_id, campaign_id=None, profile_id=None,
                assigned_membership_id=None,
                created_by_membership_id=context.access.membership_id,
                title="Next store visit", description=None, due_at=now + timedelta(days=2),
                priority="normal", status="in_progress", completed_at=None,
            ),
            CRMWorkItem(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                opportunity_id=eur_id, campaign_id=None, profile_id=None,
                assigned_membership_id=context.access.membership_id,
                created_by_membership_id=context.access.membership_id,
                title="Completed proposal review", description=None, due_at=now - timedelta(days=2),
                priority="low", status="completed", completed_at=now - timedelta(days=1),
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Sales dashboard viewer {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.opportunity:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:view"),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/sales-operations",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"organization_unit_id": str(root_id), "pipeline_id": str(pipeline_id)},
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["follow_up_coverage"] == {
            "opportunity_count": 3,
            "with_open_follow_up_count": 1,
            "without_open_follow_up_count": 2,
        }
        assert report["work_queue"]["status_counts"] == {
            "completed": 1, "in_progress": 1, "open": 1,
        }
        assert report["work_queue"]["active_count"] == 2
        assert report["work_queue"]["overdue_active_count"] == 1
        assert report["work_queue"]["unassigned_active_count"] == 1
        assert report["work_queue"]["due_in_next_seven_days_count"] == 1
        assert report["work_queue"]["active_by_priority"] == {"high": 1, "normal": 1}

        qualified = next(stage for stage in report["opportunities_by_stage"]
                         if stage["stage_key"] == "qualified")
        assert qualified["opportunity_count"] == 2
        assert qualified["unpriced_opportunity_count"] == 1
        assert qualified["amount_by_currency"] == {"USD": "1000.000000"}
        assert qualified["probability_percent"] == 60

        proposal = next(stage for stage in report["opportunities_by_stage"]
                        if stage["stage_key"] == "proposal")
        assert proposal["opportunity_count"] == 1
        assert proposal["amount_by_currency"] == {"EUR": "500.000000"}
        assert proposal["probability_percent"] is None

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        event = await context.session.scalar(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_sales_operations_dashboard.viewed",
        ))
        assert event is not None
        assert event.after_state["opportunity_count"] == 3


@pytest.mark.asyncio
async def test_sales_operations_dashboard_requires_both_view_permissions(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/sales-operations",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"organization_unit_id": str(root_id), "pipeline_id": str(uuid4())},
        )
    assert response.status_code == 403
