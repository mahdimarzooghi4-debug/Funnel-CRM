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
                    attributed_revenue_amount=Decimal("80"), attributed_revenue_currency="EUR",
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
            "EUR": "120.000000", "USD": "100.000000"
        }
        efficiency = result["totals"]["efficiency"]
        assert efficiency["cost_per_lead_by_currency"]["USD"] == {
            "paired_campaign_days": 2,
            "spend_amount": "50.000000",
            "outcome_count": 7,
            "cost_per_outcome": "7.142857",
        }
        assert efficiency["cost_per_conversion_by_currency"]["USD"] == {
            "paired_campaign_days": 2,
            "spend_amount": "50.000000",
            "outcome_count": 3,
            "cost_per_outcome": "16.666667",
        }
        assert efficiency["cost_per_conversion_by_currency"]["EUR"]["cost_per_outcome"] == "10.000000"
        assert efficiency["roas_by_currency"] == {
            "EUR": {
                "paired_campaign_days": 1,
                "spend_amount": "10.000000",
                "attributed_revenue_amount": "40.000000",
                "return_multiple": "4.000000",
            },
            "USD": {
                "paired_campaign_days": 1,
                "spend_amount": "20.000000",
                "attributed_revenue_amount": "100.000000",
                "return_multiple": "5.000000",
            },
        }
        assert [item["name"] for item in result["campaigns"]] == [
            "Web acquisition", "Store retention"
        ]
        web_efficiency = result["campaigns"][0]["efficiency"]
        assert web_efficiency["cost_per_lead_by_currency"]["USD"]["cost_per_outcome"] == "4.000000"
        assert web_efficiency["roas_by_currency"]["EUR"]["return_multiple"] == "4.000000"
        assert "USD" not in result["campaigns"][1]["efficiency"]["roas_by_currency"]
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

        comparison = await client.get(
            "/api/v1/crm/analytics/campaign-performance/comparison",
            headers=headers,
            params={
                "current_period_start": "2026-10-17",
                "current_period_end": "2026-10-17",
                "comparison_period_start": "2026-10-16",
                "comparison_period_end": "2026-10-16",
                "grouped_by": "channel",
            },
        )
        assert comparison.status_code == 200, comparison.text
        comparison_result = comparison.json()
        click_change = comparison_result["total"]["change"]["totals"]["clicks"]
        assert click_change == {
            "current_value": 25,
            "comparison_value": 70,
            "absolute_change": -45,
            "percent_change": -64.2857,
            "comparable": True,
        }
        usd_spend_change = comparison_result["total"]["change"]["actual_spend_by_currency"]["USD"]
        assert usd_spend_change == {
            "current_value": None,
            "comparison_value": "50.000000",
            "absolute_change": None,
            "percent_change": None,
            "comparable": False,
        }
        group_comparison = {item["key"]: item for item in comparison_result["groups"]}
        assert group_comparison["web"]["change"]["totals"]["clicks"]["absolute_change"] == -25
        assert group_comparison["store"]["current"] is None
        assert group_comparison["store"]["change"]["totals"]["clicks"]["comparable"] is False

        unequal_periods = await client.get(
            "/api/v1/crm/analytics/campaign-performance/comparison",
            headers=headers,
            params={
                "current_period_start": "2026-10-16",
                "current_period_end": "2026-10-17",
                "comparison_period_start": "2026-10-16",
                "comparison_period_end": "2026-10-16",
            },
        )
        assert unequal_periods.status_code == 422

        overlapping_periods = await client.get(
            "/api/v1/crm/analytics/campaign-performance/comparison",
            headers=headers,
            params={
                "current_period_start": "2026-10-16",
                "current_period_end": "2026-10-17",
                "comparison_period_start": "2026-10-17",
                "comparison_period_end": "2026-10-18",
            },
        )
        assert overlapping_periods.status_code == 422

        invalid_period = await client.get(
            "/api/v1/crm/analytics/campaign-performance/portfolio",
            headers=headers,
            params={"period_start": "2026-10-18", "period_end": "2026-10-16"},
        )
        assert invalid_period.status_code == 422
