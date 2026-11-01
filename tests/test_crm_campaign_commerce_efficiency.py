from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_commerce_efficiency import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
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
async def test_campaign_efficiency_matches_spend_and_explicit_commerce_links_by_currency(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    campaign_id, segment_id = uuid4(), uuid4()
    fact_ids = [uuid4(), uuid4(), uuid4()]
    measured_on = date(2026, 10, 19)
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Efficiency segment {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        role = Role(tenant_id=tenant_id, name=f"Efficiency analyst {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Efficiency test campaign",
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
        context.session.add_all([
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=measured_on,
                source_label="approved test source",
                actual_spend_amount=Decimal("100.00"), actual_spend_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=measured_on.replace(day=18),
                source_label="approved test source",
                actual_spend_amount=Decimal("20.00"), actual_spend_currency="EUR",
            ),
            CRMProductCommerceEvent(
                id=fact_ids[0], tenant_id=tenant_id,
                organization_unit_id=root_id, campaign_id=campaign_id,
                profile_id=None, source_product="funnel.store",
                source_event_id=uuid4(), event_type="commerce.order.paid",
                order_reference="ORDER-1", event_kind="paid",
                amount=Decimal("250.00"), currency="USD",
                occurred_at=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
            ),
            CRMProductCommerceEvent(
                id=fact_ids[1], tenant_id=tenant_id,
                organization_unit_id=root_id, campaign_id=campaign_id,
                profile_id=None, source_product="funnel.store",
                source_event_id=uuid4(), event_type="commerce.order.refunded",
                order_reference="ORDER-1", event_kind="refunded",
                amount=Decimal("25.00"), currency="USD",
                occurred_at=datetime(2026, 10, 19, 13, tzinfo=timezone.utc),
            ),
            CRMProductCommerceEvent(
                id=fact_ids[2], tenant_id=tenant_id,
                organization_unit_id=root_id, campaign_id=campaign_id,
                profile_id=None, source_product="funnel.online",
                source_event_id=uuid4(), event_type="commerce.order.paid",
                order_reference="ORDER-EUR", event_kind="paid",
                amount=Decimal("10.00"), currency="EUR",
                occurred_at=datetime(2026, 10, 19, 14, tzinfo=timezone.utc),
            ),
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id,
                organization_unit_id=root_id, campaign_id=None,
                profile_id=None, source_product="funnel.store",
                source_event_id=uuid4(), event_type="commerce.order.paid",
                order_reference="UNLINKED-ORDER", event_kind="paid",
                amount=Decimal("999.00"), currency="USD",
                occurred_at=datetime(2026, 10, 19, 15, tzinfo=timezone.utc),
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/campaign-commerce-efficiency",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={
                "organization_unit_id": str(root_id),
                "campaign_id": str(campaign_id),
                "period_start": "2026-10-01",
                "period_end": "2026-10-31",
            },
        )
        assert response.status_code == 200, response.text
        report = response.json()

    assert report["causal_attribution_applied"] is False
    assert report["currency_conversion_applied"] is False
    assert report["total_campaign_count"] == 1
    assert len(report["campaigns"]) == 1
    metrics = {
        row["currency"]: row for row in report["campaigns"][0]["currency_metrics"]
    }
    assert set(metrics) == {"USD", "EUR"}
    assert Decimal(metrics["USD"]["spend_amount"]) == Decimal("100.00")
    assert Decimal(metrics["USD"]["paid_amount"]) == Decimal("250.00")
    assert Decimal(metrics["USD"]["refunded_amount"]) == Decimal("25.00")
    assert Decimal(metrics["USD"]["net_paid_amount"]) == Decimal("225.00")
    assert Decimal(metrics["USD"]["net_paid_amount_per_paid_order"]) == Decimal("225.000000")
    assert Decimal(metrics["USD"]["observed_paid_to_spend_multiple"]) == Decimal("2.500000")
    assert Decimal(metrics["USD"]["observed_net_paid_to_spend_multiple"]) == Decimal("2.250000")
    assert Decimal(metrics["USD"]["observed_refunds_to_spend_multiple"]) == Decimal("0.250000")
    assert Decimal(metrics["EUR"]["spend_amount"]) == Decimal("20.00")
    assert Decimal(metrics["EUR"]["paid_amount"]) == Decimal("10.00")
    assert Decimal(metrics["EUR"]["net_paid_amount"]) == Decimal("10.00")
    assert Decimal(metrics["EUR"]["net_paid_amount_per_paid_order"]) == Decimal("10.000000")
    assert Decimal(metrics["EUR"]["observed_net_paid_to_spend_multiple"]) == Decimal("0.500000")
    assert Decimal(metrics["EUR"]["observed_paid_to_spend_multiple"]) == Decimal("0.500000")
    assert "net_revenue" not in report

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        audit = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_campaign.commerce_efficiency_report_viewed",
        ))).all()
        assert len(audit) == 1
        await context.session.execute(delete(CRMProductCommerceEvent).where(
            CRMProductCommerceEvent.tenant_id == tenant_id,
            CRMProductCommerceEvent.campaign_id == campaign_id,
        ))
        await context.session.execute(delete(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == tenant_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign_id,
        ))
        await context.session.execute(delete(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        ))
        await context.session.execute(delete(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == tenant_id,
            CRMProfileSegment.id == segment_id,
        ))
