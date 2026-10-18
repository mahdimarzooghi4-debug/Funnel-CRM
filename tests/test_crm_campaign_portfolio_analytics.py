from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_portfolio_analytics import router
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
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
async def test_campaign_portfolio_analytics_groups_observed_results_without_currency_conversion(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id = uuid4()
    first_id, second_id, unmeasured_id = uuid4(), uuid4(), uuid4()
    campaigns = [
        CRMMarketingCampaign(
            id=first_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Web acquisition", objective_key="acquisition",
            channel="web", planned_budget_amount=Decimal("500"),
            planned_budget_currency="USD", starts_at=None, ends_at=None, status="draft",
        ),
        CRMMarketingCampaign(
            id=second_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Store retention", objective_key="retention",
            channel="store", planned_budget_amount=Decimal("300"),
            planned_budget_currency="EUR", starts_at=None, ends_at=None, status="archived",
        ),
        CRMMarketingCampaign(
            id=unmeasured_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Unmeasured campaign", objective_key="acquisition",
            channel="email", planned_budget_amount=None, planned_budget_currency=None,
            starts_at=None, ends_at=None, status="draft",
        ),
    ]

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(
            CRMProfileSegment(
                id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
                name=f"Portfolio analytics audience {uuid4().hex[:8]}",
                criteria={"profile_kinds": ["person"]}, is_active=True,
            )
        )
        await context.session.flush()
        context.session.add_all(campaigns)
        await context.session.flush()
        context.session.add_all(
            [
                CRMMarketingCampaignMeasurement(
                    id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                    campaign_id=first_id, measured_on=date(2026, 10, 16),
                    source_label="web analytics", impressions=1000, reach=700,
                    clicks=50, responses=8, leads=5, conversions=2,
                    actual_spend_amount=Decimal("20"), actual_spend_currency="USD",
                    attributed_revenue_amount=Decimal("100"), attributed_revenue_currency="USD",
                ),
                CRMMarketingCampaignMeasurement(
                    id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                    campaign_id=first_id, measured_on=date(2026, 10, 17),
                    source_label="web analytics", impressions=500, reach=400,
                    clicks=25, responses=None, leads=4, conversions=1,
                    actual_spend_amount=Decimal("10"), actual_spend_currency="EUR",
                    attributed_revenue_amount=Decimal("40"), attributed_revenue_currency="EUR",
                ),
                CRMMarketingCampaignMeasurement(
                    id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                    campaign_id=second_id, measured_on=date(2026, 10, 16),
                    source_label="store tally", impressions=2000, reach=1500,
                    clicks=20, responses=10, leads=2, conversions=1,
                    actual_spend_amount=Decimal("30"), actual_spend_currency="USD",
                    attributed_revenue_amount=Decimal("80"), attributed_revenue_currency="USD",
                ),
            ]
        )
        role = Role(tenant_id=tenant_id, name=f"Portfolio analyst {uuid4().hex[:8]}")
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
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/campaign-performance/portfolio",
            headers=headers,
            params={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "grouped_by": "channel",
                "sort_by": "conversions",
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["totals"]["campaign_count"] == 2
        assert result["totals"]["measurement_record_count"] == 3
        assert result["totals"]["totals"] == {
            "impressions": 3500,
            "reach": 2600,
            "clicks": 95,
            "responses": 18,
            "leads": 11,
            "conversions": 4,
        }
        assert result["totals"]["click_through_rate_percent"] == 2.7143
        assert result["totals"]["lead_rate_per_click_percent"] == 11.5789
        assert result["totals"]["conversion_rate_per_click_percent"] == 4.2105
        assert result["totals"]["planned_budget_by_currency"] == {
            "EUR": "300.000000", "USD": "500.000000"
        }
        assert result["totals"]["actual_spend_by_currency"] == {
            "EUR": "10.000000", "USD": "50.000000"
        }
        assert result["totals"]["attributed_revenue_by_currency"] == {
            "EUR": "40.000000", "USD": "180.000000"
        }
        assert [item["name"] for item in result["campaigns"]] == [
            "Web acquisition", "Store retention"
        ]
        assert result["campaign_list_truncated"] is False
        assert {item["key"] for item in result["groups"]} == {"store", "web"}
        assert all(item["metrics"]["campaign_count"] == 1 for item in result["groups"])

        objective_report = await client.get(
            "/api/v1/crm/analytics/campaign-performance/portfolio",
            headers=headers,
            params={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "grouped_by": "objective",
                "sort_by": "clicks",
                "limit": 1,
            },
        )
        assert objective_report.status_code == 200, objective_report.text
        objective = objective_report.json()
        assert {item["key"] for item in objective["groups"]} == {
            "acquisition", "retention"
        }
        assert [item["name"] for item in objective["campaigns"]] == [
            "Web acquisition"
        ]
        assert objective["campaign_list_truncated"] is True

        invalid_period = await client.get(
            "/api/v1/crm/analytics/campaign-performance/portfolio",
            headers=headers,
            params={"period_start": "2026-10-18", "period_end": "2026-10-16"},
        )
        assert invalid_period.status_code == 422
