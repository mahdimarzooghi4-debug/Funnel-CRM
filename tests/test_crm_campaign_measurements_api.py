from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_measurements import router
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
async def test_campaign_measurements_upsert_and_report_observed_metrics_and_money(
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
        context.session.add(
            CRMProfileSegment(
                id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
                name=f"Measurement audience {uuid4().hex[:8]}",
                criteria={"profile_kinds": ["person"]}, is_active=True,
            )
        )
        await context.session.flush()
        campaign = CRMMarketingCampaign(
            id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Measurement campaign", objective_key="acquisition",
            channel="web", planned_budget_amount=Decimal("500"),
            planned_budget_currency="USD", starts_at=None, ends_at=None, status="draft",
        )
        role = Role(tenant_id=tenant_id, name=f"Measurement manager {uuid4().hex[:8]}")
        context.session.add_all([campaign, role])
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
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    first_day, second_day = date(2026, 10, 16), date(2026, 10, 17)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.put(
            f"/api/v1/crm/campaigns/{campaign_id}/measurements/{first_day.isoformat()}",
            headers=headers,
            json={
                "source_label": "web analytics",
                "impressions": 1000,
                "reach": 700,
                "clicks": 50,
                "leads": 5,
                "conversions": 2,
                "assigned_count": 120,
                "exposure_count": 100,
                "actual_spend_amount": "20",
                "actual_spend_currency": "USD",
                "attributed_revenue_amount": "100",
                "attributed_revenue_currency": "USD",
            },
        )
        assert first.status_code == 200, first.text
        measurement_id = first.json()["id"]
        assert first.json()["assigned_count"] == 120
        assert first.json()["exposure_count"] == 100

        updated = await client.put(
            f"/api/v1/crm/campaigns/{campaign_id}/measurements/{first_day.isoformat()}",
            headers=headers,
            json={
                "source_label": "web analytics corrected",
                "impressions": 1000,
                "reach": 700,
                "clicks": 50,
                "responses": 8,
                "leads": 5,
                "conversions": 2,
                "assigned_count": 120,
                "exposure_count": 110,
                "actual_spend_amount": "20",
                "actual_spend_currency": "USD",
                "attributed_revenue_amount": "100",
                "attributed_revenue_currency": "USD",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["id"] == measurement_id
        assert updated.json()["responses"] == 8

        second = await client.put(
            f"/api/v1/crm/campaigns/{campaign_id}/measurements/{second_day.isoformat()}",
            headers=headers,
            json={
                "source_label": "web analytics",
                "impressions": 500,
                "reach": 400,
                "clicks": 25,
                "leads": 4,
                "conversions": 1,
                "assigned_count": 50,
                "exposure_count": 45,
                "actual_spend_amount": "10",
                "actual_spend_currency": "EUR",
                "attributed_revenue_amount": "40",
                "attributed_revenue_currency": "EUR",
            },
        )
        assert second.status_code == 200, second.text

        summary = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/measurements/summary",
            headers=headers,
            params={"period_start": first_day.isoformat(), "period_end": second_day.isoformat()},
        )
        assert summary.status_code == 200, summary.text
        report = summary.json()
        assert report["record_count"] == 2
        assert report["source_labels"] == ["web analytics", "web analytics corrected"]
        assert report["totals"] == {
            "impressions": 1500,
            "reach": 1100,
            "clicks": 75,
            "responses": 8,
            "leads": 9,
            "conversions": 3,
            "assigned_count": 170,
            "exposure_count": 155,
        }
        assert report["coverage_days"]["responses"] == 1
        assert report["coverage_days"]["assigned_count"] == 2
        assert report["coverage_days"]["exposure_count"] == 2
        assert report["click_through_rate_percent"] == 5.0
        assert report["lead_rate_per_click_percent"] == 12.0
        assert report["conversion_rate_per_click_percent"] == 4.0
        assert report["actual_spend_by_currency"] == {"EUR": "10.000000", "USD": "20.000000"}
        assert report["attributed_revenue_by_currency"] == {"EUR": "40.000000", "USD": "100.000000"}

        invalid = await client.put(
            f"/api/v1/crm/campaigns/{campaign_id}/measurements/{date(2026, 10, 18).isoformat()}",
            headers=headers,
            json={
                "source_label": " ",
                "impressions": -1,
            },
        )
        assert invalid.status_code == 422

        invalid_delivery_count = await client.put(
            f"/api/v1/crm/campaigns/{campaign_id}/measurements/{date(2026, 10, 19).isoformat()}",
            headers=headers,
            json={"source_label": "invalid export", "assigned_count": -1},
        )
        assert invalid_delivery_count.status_code == 422

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        stored = await context.session.scalar(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.id == campaign_id,
            )
        )
        assert stored is not None
        assert (stored.planned_budget_amount, stored.planned_budget_currency) == (
            Decimal("500"), "USD"
        )
