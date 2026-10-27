from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_decision_workspace import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMProfileSegment,
    CRMProductCommerceEvent,
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
async def test_campaign_decision_workspace_shows_targets_coverage_and_linked_outcomes(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    campaign_id, plan_id, segment_id = uuid4(), uuid4(), uuid4()
    period_start, period_end = date(2026, 10, 19), date(2026, 10, 25)
    event_fact_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Decision workspace segment {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        role = Role(tenant_id=tenant_id, name=f"Decision analyst {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Decision workspace campaign",
                objective_key="acquisition", channel="web",
                planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
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
        context.session.add(CRMMarketingCampaignTargetPlan(
            id=plan_id, tenant_id=tenant_id, organization_unit_id=root_id,
            campaign_id=campaign_id, period_start=period_start, period_end=period_end,
            impressions_target=80, clicks_target=10, leads_target=None,
            conversions_target=None,
            max_spend_amount=Decimal("70.00"), max_spend_currency="USD",
            max_cpl_amount=None, cpl_currency=None,
            max_cost_per_conversion_amount=None, conversion_cost_currency=None,
            min_roas=Decimal("1.500000"), roas_currency="USD",
            min_net_paid_to_spend=Decimal("2.000000"), net_paid_to_spend_currency="USD",
        ))
        context.session.add_all([
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 19),
                source_label="verified analytics import",
                impressions=60, clicks=5, reach=None, responses=None,
                leads=None, conversions=None,
                actual_spend_amount=Decimal("40.00"), actual_spend_currency="USD",
                attributed_revenue_amount=None, attributed_revenue_currency=None,
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 20),
                source_label="verified analytics import",
                impressions=20, clicks=2, reach=None, responses=None,
                leads=None, conversions=None,
                actual_spend_amount=Decimal("20.00"), actual_spend_currency="USD",
                attributed_revenue_amount=None, attributed_revenue_currency=None,
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 21),
                source_label="verified analytics import",
                impressions=None, clicks=None, reach=None, responses=None,
                leads=None, conversions=None,
                actual_spend_amount=Decimal("10.00"), actual_spend_currency="EUR",
                attributed_revenue_amount=None, attributed_revenue_currency=None,
            ),
        ])
        for index, (kind, amount, currency, order_ref) in enumerate([
            ("paid", "80.00", "USD", "USD-1"),
            ("paid", "40.00", "USD", "USD-2"),
            ("refunded", "10.00", "USD", "USD-1"),
            ("paid", "6.00", "EUR", "EUR-1"),
        ]):
            context.session.add(CRMProductCommerceEvent(
                id=event_fact_ids[index], tenant_id=tenant_id,
                organization_unit_id=root_id, campaign_id=campaign_id,
                profile_id=None, source_product="funnel.marketplace" if order_ref == "USD-2" else "funnel.store",
                source_event_id=uuid4(),
                event_type="commerce.order.refunded" if kind == "refunded" else "commerce.order.paid",
                order_reference=order_ref, event_kind=kind,
                amount=Decimal(amount), currency=currency,
                occurred_at=datetime(2026, 10, 19, 10 + index, tzinfo=timezone.utc),
            ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/decision-workspace/{plan_id}",
            headers={"X-Workspace-ID": str(tenant_id)},
        )
        assert response.status_code == 200, response.text
        workspace = response.json()
        queue_response = await client.get(
            "/api/v1/crm/campaigns/decision-queue",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
                    "organization_unit_id": str(root_id)},
        )
        assert queue_response.status_code == 200, queue_response.text
        queue = queue_response.json()

    assert workspace["campaign_name"] == "Decision workspace campaign"
    assert workspace["period_calendar_days"] == 7
    assert workspace["causal_attribution_applied"] is False
    assert workspace["automatic_recommendation_issued"] is False
    assert workspace["metrics"]["impressions"]["actual"] == 80
    assert workspace["metrics"]["impressions"]["status"] == "met"
    assert Decimal(workspace["metrics"]["impressions"]["recorded_day_coverage_percent"]) == Decimal("28.57")
    assert workspace["metrics"]["clicks"]["actual"] == 7
    assert workspace["metrics"]["clicks"]["status"] == "not_met"
    assert workspace["metrics"]["spend"]["actual"] == "60.000000"
    assert workspace["metrics"]["spend"]["status"] == "met"
    assert workspace["metrics"]["paid_to_spend"]["actual"] == "2.000000"
    assert workspace["metrics"]["paid_to_spend"]["status"] == "met"
    assert workspace["metrics"]["period_net_paid_to_spend"]["actual"] == "1.833333"
    assert workspace["metrics"]["period_net_paid_to_spend"]["status"] == "not_met"
    assert workspace["metric_definitions"]["spend"]["key"] == "actual_spend"
    assert workspace["metric_definitions"]["impressions"]["key"] == "impressions"
    assert workspace["metric_definitions"]["paid_to_spend"]["key"] == "paid_to_spend"
    assert workspace["metric_definitions"]["net_paid_amount"]["key"] == "net_paid_amount"
    assert workspace["metric_definitions"]["net_paid_amount_per_paid_order"]["key"] == "net_paid_amount_per_paid_order"
    assert workspace["metric_definitions"]["period_net_paid_to_spend"]["key"] == "period_net_paid_to_spend"
    assert "not accounting profit" in workspace["commerce_basis"]
    assert "بازده علّی تبلیغ" in workspace["metric_definitions"]["paid_to_spend"]["limitations"]
    assert workspace["coverage_definition"]["key"] == "recorded_day_coverage"
    currency_rows = {
        row["currency"]: row for row in workspace["commerce_outcomes_by_currency"]
    }
    assert set(currency_rows) == {"USD", "EUR"}
    assert currency_rows["USD"]["paid_event_count"] == 2
    assert currency_rows["USD"]["paid_order_count"] == 2
    assert currency_rows["USD"]["paid_amount"] == "120.000000"
    assert currency_rows["USD"]["refunded_amount"] == "10.000000"
    assert currency_rows["USD"]["net_paid_amount"] == "110.000000"
    assert currency_rows["USD"]["net_paid_amount_per_paid_order"] == "55.000000"
    assert currency_rows["USD"]["observed_paid_to_spend_multiple"] == "2.000000"
    assert currency_rows["USD"]["observed_net_paid_to_spend_multiple"] == "1.833333"
    assert currency_rows["EUR"]["paid_amount"] == "6.000000"
    assert currency_rows["EUR"]["net_paid_amount"] == "6.000000"
    assert currency_rows["EUR"]["net_paid_amount_per_paid_order"] == "6.000000"
    source_rows = {
        (row["source_product"], row["currency"]): row
        for row in workspace["commerce_outcomes_by_source_product"]
    }
    assert source_rows[("funnel.store", "USD")]["net_paid_amount"] == "70.000000"
    assert source_rows[("funnel.store", "USD")]["net_paid_amount_per_paid_order"] == "70.000000"
    assert source_rows[("funnel.marketplace", "USD")]["paid_amount"] == "40.000000"
    assert source_rows[("funnel.marketplace", "USD")]["net_paid_amount"] == "40.000000"
    assert source_rows[("funnel.marketplace", "USD")]["net_paid_amount_per_paid_order"] == "40.000000"
    assert source_rows[("funnel.store", "EUR")]["net_paid_amount"] == "6.000000"
    assert queue["total_count"] == 1
    assert queue["automatic_recommendation_issued"] is False
    assert queue["items"][0]["target_plan_id"] == str(plan_id)
    assert queue["items"][0]["status"] == "review_required"
    assert queue["items"][0]["missed_metric_count"] == 2
    assert set(queue["items"][0]["attention_reasons"]) == {
        "target_missed", "net_commerce_target_missed", "low_recorded_day_coverage"
    }

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        audits = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_campaign.decision_workspace_viewed",
            AuditEvent.target_key == str(plan_id),
        ))).all()
        assert len(audits) == 1
        await context.session.execute(delete(CRMProductCommerceEvent).where(
            CRMProductCommerceEvent.tenant_id == tenant_id,
            CRMProductCommerceEvent.campaign_id == campaign_id,
        ))
        await context.session.execute(delete(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == tenant_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign_id,
        ))
        await context.session.execute(delete(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == tenant_id,
            CRMMarketingCampaignTargetPlan.id == plan_id,
        ))
        await context.session.execute(delete(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        ))
        await context.session.execute(delete(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == tenant_id,
            CRMProfileSegment.id == segment_id,
        ))
