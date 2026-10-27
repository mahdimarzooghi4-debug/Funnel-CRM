from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_targets import evaluate_net_paid_to_spend_target, router
from funnel_crm.api.v1.crm_campaign_target_analytics import router as target_analytics_router
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMProductCommerceEvent,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def test_net_paid_to_spend_target_subtracts_refunds_and_keeps_currencies_separate() -> None:
    tenant_id, organization_unit_id, campaign_id = uuid4(), uuid4(), uuid4()
    plan = CRMMarketingCampaignTargetPlan(
        id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
        campaign_id=campaign_id, period_start=date(2026, 10, 16), period_end=date(2026, 10, 17),
        min_net_paid_to_spend=Decimal("4.5"), net_paid_to_spend_currency="USD",
    )
    measurement = CRMMarketingCampaignMeasurement(
        id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
        campaign_id=campaign_id, measured_on=date(2026, 10, 16), source_label="test",
        actual_spend_amount=Decimal("20"), actual_spend_currency="USD",
    )
    events = [
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
            campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
            source_event_id=uuid4(), event_type="commerce.order.paid", order_reference="A",
            event_kind="paid", amount=Decimal("100"), currency="USD",
            occurred_at=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
            campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
            source_event_id=uuid4(), event_type="commerce.order.refunded", order_reference="A",
            event_kind="refunded", amount=Decimal("10"), currency="USD",
            occurred_at=datetime(2026, 10, 16, 13, tzinfo=timezone.utc),
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
            campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
            source_event_id=uuid4(), event_type="commerce.order.paid", order_reference="B",
            event_kind="paid", amount=Decimal("1000"), currency="EUR",
            occurred_at=datetime(2026, 10, 16, 14, tzinfo=timezone.utc),
        ),
    ]

    result = evaluate_net_paid_to_spend_target(plan, [measurement], events)

    assert result is not None
    assert result.actual == Decimal("4.500000")
    assert result.status == "met"


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
    app.include_router(target_analytics_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_campaign_targets_upsert_and_evaluation_use_currency_matched_observations(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id, campaign_id, partial_campaign_id, campaign_without_measurements_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Targets audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Acquisition", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=partial_campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Partial acquisition", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=campaign_without_measurements_id, tenant_id=tenant_id,
                organization_unit_id=root_id, segment_id=segment_id,
                name="Acquisition follow-up", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 16),
                source_label="analytics", impressions=1000, clicks=50, leads=5, conversions=2,
                actual_spend_amount=Decimal("20"), actual_spend_currency="USD",
                attributed_revenue_amount=Decimal("100"), attributed_revenue_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 17),
                source_label="analytics", impressions=500, clicks=25, leads=4, conversions=1,
                actual_spend_amount=Decimal("10"), actual_spend_currency="EUR",
                attributed_revenue_amount=Decimal("40"), attributed_revenue_currency="EUR",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=partial_campaign_id, measured_on=date(2026, 10, 16),
                source_label="analytics", impressions=None, clicks=None, leads=2,
                conversions=None, actual_spend_amount=None, actual_spend_currency=None,
                attributed_revenue_amount=None, attributed_revenue_currency=None,
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Target manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:manage"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.commerce_event:view"),
        ])
        await context.session.flush()
        for kind, amount, order_ref in (("paid", "100.00", "ORDER-1"), ("refunded", "10.00", "ORDER-1")):
            context.session.add(CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
                source_event_id=uuid4(), event_type=(
                    "commerce.order.paid" if kind == "paid" else "commerce.order.refunded"
                ), order_reference=order_ref, event_kind=kind,
                amount=Decimal(amount), currency="USD",
                occurred_at=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
            ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = f"/api/v1/crm/campaigns/{campaign_id}/targets"
        payload = {
            "period_start": "2026-10-16",
            "period_end": "2026-10-17",
            "impressions_target": 1200,
            "clicks_target": 80,
            "leads_target": 12,
            "max_spend_amount": "40",
            "max_spend_currency": "USD",
            "max_cpl_amount": "5",
            "cpl_currency": "USD",
            "max_cost_per_conversion_amount": "10",
            "conversion_cost_currency": "USD",
            "min_roas": "4",
            "roas_currency": "USD",
            "min_net_paid_to_spend": "4.5",
            "net_paid_to_spend_currency": "USD",
        }
        saved = await client.put(base, headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        target_id = saved.json()["id"]

        listing = await client.get(base, headers=headers)
        assert listing.status_code == 200, listing.text
        assert len(listing.json()) == 1

        evaluation = await client.get(f"{base}/{target_id}/evaluation", headers=headers)
        assert evaluation.status_code == 200, evaluation.text
        metrics = evaluation.json()["metrics"]
        assert metrics["impressions"]["actual"] == 1500
        assert metrics["impressions"]["status"] == "met"
        assert metrics["impressions"]["period_days"] == 2
        assert metrics["impressions"]["recorded_day_coverage_percent"] == "100.00"
        assert metrics["clicks"]["actual"] == 75
        assert metrics["clicks"]["status"] == "not_met"
        assert metrics["spend"]["actual"] == "20.000000"
        assert metrics["spend"]["observed_days"] == 1
        assert metrics["spend"]["period_days"] == 2
        assert metrics["spend"]["recorded_day_coverage_percent"] == "50.00"
        assert metrics["cost_per_lead"]["actual"] == "4.000000"
        assert metrics["cost_per_lead"]["paired_days"] == 1
        assert metrics["cost_per_conversion"]["actual"] == "10.000000"
        assert metrics["roas"]["actual"] == "5.000000"
        assert metrics["roas"]["status"] == "met"
        assert metrics["period_net_paid_to_spend"]["actual"] == "4.500000"
        assert metrics["period_net_paid_to_spend"]["status"] == "met"

        partial_campaign_target = await client.put(
            f"/api/v1/crm/campaigns/{partial_campaign_id}/targets",
            headers=headers,
            json={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "leads_target": 8,
            },
        )
        assert partial_campaign_target.status_code == 200, partial_campaign_target.text

        campaign_without_measurements_target = await client.put(
            f"/api/v1/crm/campaigns/{campaign_without_measurements_id}/targets",
            headers=headers,
            json={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "leads_target": 10,
            },
        )
        assert campaign_without_measurements_target.status_code == 200, campaign_without_measurements_target.text

        portfolio = await client.get(
            "/api/v1/crm/analytics/campaign-target-performance/portfolio",
            headers=headers,
            params={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "grouped_by": "channel",
            },
        )
        assert portfolio.status_code == 200, portfolio.text
        report = portfolio.json()
        assert report["campaign_count"] == 3
        assert report["metric_outcomes"]["impressions"] == {
            "evaluated": 1, "met": 1, "not_met": 0, "no_data": 0,
        }
        assert report["metric_outcomes"]["clicks"] == {
            "evaluated": 1, "met": 0, "not_met": 1, "no_data": 0,
        }
        assert report["groups"][0]["key"] == "web"
        assert report["metric_variances"]["leads"] == {
            "targeted_campaign_count": 3,
            "complete_campaign_count": 1,
            "incomplete_campaign_count": 2,
            "target_total": 30,
            "complete_actual_total": 9,
            "complete_campaign_target_total": 12,
            "complete_variance": -3,
            "incomplete_target_total": 18,
            "partial_actual_total": 2,
        }
        assert report["groups"][0]["metric_variances"]["leads"]["incomplete_target_total"] == 18
        assert report["campaigns"][0]["metrics"]["roas"]["currency"] == "USD"
        assert report["period_calendar_days"] == 2
        assert report["metric_definitions"]["roas"]["key"] == "reported_roas"
        assert report["metric_outcomes"]["period_net_paid_to_spend"]["met"] == 1
        assert report["metric_definitions"]["spend"]["key"] == "actual_spend"
        assert report["campaigns"][0]["metrics"]["spend"]["recorded_day_coverage_percent"] == "50.00"
        assert "missing days are not zero" in report["coverage_basis"]

        payload["clicks_target"] = 70
        updated = await client.put(base, headers=headers, json=payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()["id"] == target_id
        assert len((await client.get(base, headers=headers)).json()) == 1

        invalid = await client.put(base, headers=headers, json={
            "period_start": "2026-01-01",
            "period_end": "2027-01-02",
            "leads_target": 10,
        })
        assert invalid.status_code == 422
