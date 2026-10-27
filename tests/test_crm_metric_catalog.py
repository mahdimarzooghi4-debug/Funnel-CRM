from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_metric_catalog import _METRICS, _visible_metrics, router
from funnel_crm.platform.models import AuditEvent, Role, RoleAssignment, RolePermission
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


def test_metric_catalog_distinguishes_commerce_evidence_and_filters_by_permission() -> None:
    campaign_only = _visible_metrics(
        _METRICS, has_commerce_permission=False, category=None, search=None
    )
    with_commerce = _visible_metrics(
        _METRICS, has_commerce_permission=True, category=None, search=None
    )
    assert {metric.key for metric in campaign_only}.isdisjoint(
        {"paid_amount", "paid_order_count", "average_paid_order_value", "average_refund_per_order", "refund_to_paid_amount_percent", "refund_amount", "refunded_order_count", "refunded_order_rate_percent", "paid_to_spend"}
    )
    assert {"paid_amount", "paid_order_count", "average_paid_order_value", "average_refund_per_order", "refund_to_paid_amount_percent", "refund_amount", "refunded_order_count", "refunded_order_rate_percent", "paid_to_spend"} <= {
        metric.key for metric in with_commerce
    }
    reported_roas = next(metric for metric in with_commerce if metric.key == "reported_roas")
    paid_to_spend = next(metric for metric in with_commerce if metric.key == "paid_to_spend")
    assert "attributed_revenue_amount" in reported_roas.source
    assert "CRMProductCommerceEvent" in paid_to_spend.source
    assert "بازده علّی تبلیغ" in paid_to_spend.limitations


@pytest.mark.asyncio
async def test_metric_catalog_is_scoped_searchable_and_audited(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        role = Role(tenant_id=tenant_id, name=f"Metric analyst {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
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
                permission_key="crm.commerce_event:view",
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/metrics",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"organization_unit_id": str(root_id), "category": "commerce"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["catalog_version"] == "1.0"
        assert {metric["key"] for metric in body["metrics"]} == {
            "paid_amount", "paid_order_count", "average_paid_order_value", "average_refund_per_order", "refund_to_paid_amount_percent", "refund_amount", "refunded_order_count", "refunded_order_rate_percent", "paid_to_spend",
        }
        assert all(
            "crm.commerce_event:view" in metric["required_permissions"]
            for metric in body["metrics"]
        )

        search_response = await client.get(
            "/api/v1/crm/analytics/metrics",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={
                "organization_unit_id": str(root_id),
                "search": "بازده علّی تبلیغ",
            },
        )
        assert search_response.status_code == 200, search_response.text
        assert [metric["key"] for metric in search_response.json()["metrics"]] == [
            "paid_to_spend",
        ]

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        events = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_marketing.metric_catalog_viewed",
        ))).all()
        assert len(events) == 2
