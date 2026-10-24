from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_customer_lifecycle_analytics import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMMarketingCampaign,
    CRMOpportunity,
    CRMProductCommerceEvent,
    CRMProfile,
    CRMProfileSegment,
    CRMPipeline,
    Role,
    RoleAssignment,
    RolePermission,
    TenantRecord,
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
async def test_customer_lifecycle_analytics_connects_current_stage_to_period_facts(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    customer_one, customer_two, lead = uuid4(), uuid4(), uuid4()
    tenant_case["lifecycle_cleanup_profile_ids"] = (customer_one, customer_two, lead)
    segment_id, campaign_id, pipeline_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Lifecycle analytics segment {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        await context.session.flush()
        context.session.add(CRMMarketingCampaign(
            id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Lifecycle analytics campaign",
            objective_key="retention", channel="email", planned_budget_amount=None,
            planned_budget_currency=None, starts_at=None, ends_at=None, status="draft",
        ))
        for profile_id in (customer_one, customer_two, lead):
            context.session.add(TenantRecord(
                id=profile_id, tenant_id=tenant_id, organization_unit_id=root_id,
                record_type="crm_profile",
            ))
        await context.session.flush()
        context.session.add_all([
            CRMProfile(
                id=customer_one, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_kind="person", display_name="Lifecycle customer one",
                lifecycle_stage="customer",
            ),
            CRMProfile(
                id=customer_two, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_kind="person", display_name="Lifecycle customer two",
                lifecycle_stage="customer",
            ),
            CRMProfile(
                id=lead, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_kind="person", display_name="Lifecycle lead",
                lifecycle_stage="lead",
            ),
            CRMPipeline(
                id=pipeline_id, tenant_id=tenant_id,
                pipeline_key=f"lifecycle-{uuid4().hex[:8]}", entity_kind="opportunity",
                display_name="Lifecycle pipeline",
                stages=[{"key": "qualified", "name": "Qualified", "position": 1,
                         "outcome_key": "open", "probability_percent": 50}],
                is_default=False,
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=customer_one,
                source_product="funnel.store", source_event_id=uuid4(), campaign_id=campaign_id,
                activity_type="order.completed", channel="online", occurred_at=now,
            ),
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=customer_one,
                source_product="funnel.store", source_event_id=uuid4(), campaign_id=None,
                activity_type="support.resolved", channel="support", occurred_at=now,
            ),
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=lead,
                source_product="funnel.web", source_event_id=uuid4(), campaign_id=None,
                activity_type="form.submitted", channel="online", occurred_at=now,
            ),
            CRMOpportunity(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                profile_id=customer_one, pipeline_id=pipeline_id, name="Customer expansion",
                stage_key="qualified", amount=Decimal("500"), currency="USD",
                expected_close_date=date(2026, 10, 30), created_at=now,
            ),
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, profile_id=customer_one, source_product="funnel.store",
                source_event_id=uuid4(), event_type="commerce.order.paid",
                order_reference="CUST-USD-1", event_kind="paid",
                amount=Decimal("120.00"), currency="USD", occurred_at=now,
            ),
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, profile_id=customer_one, source_product="funnel.store",
                source_event_id=uuid4(), event_type="commerce.order.refunded",
                order_reference="CUST-USD-1", event_kind="refunded",
                amount=Decimal("20.00"), currency="USD", occurred_at=now,
            ),
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=None, profile_id=lead, source_product="funnel.store",
                source_event_id=uuid4(), event_type="commerce.order.paid",
                order_reference="LEAD-EUR-1", event_kind="paid",
                amount=Decimal("40.00"), currency="EUR", occurred_at=now,
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Lifecycle analyst {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            *[
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key=permission)
                for permission in (
                    "crm.profile:view", "crm.opportunity:view", "crm.commerce_event:view",
                )
            ],
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/crm/analytics/customer-lifecycle",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"period_start": "2026-10-01", "period_end": "2026-10-31"},
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["total_cohort_count"] == 2
        assert report["causal_attribution_applied"] is False
        cohorts = {row["current_lifecycle_stage"]: row for row in report["cohorts"]}
        customer_metrics = cohorts["customer"]
        assert customer_metrics["current_profile_count"] == 2
        assert customer_metrics["profiles_with_activity"] == 1
        assert customer_metrics["recorded_activity_count"] == 2
        assert customer_metrics["profiles_with_opportunity"] == 1
        assert customer_metrics["opportunity_count"] == 1
        assert customer_metrics["profiles_with_paid_event"] == 1
        assert customer_metrics["profiles_with_refund_event"] == 1
        usd = customer_metrics["commerce_by_currency"][0]
        assert usd["currency"] == "USD"
        assert usd["paid_order_count"] == 1
        assert usd["paid_amount"] == "120.000000"
        assert usd["refunded_amount"] == "20.000000"

        unauthorized = await client.get(
            "/api/v1/crm/analytics/customer-lifecycle",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"period_start": "2026-10-01", "period_end": "2026-10-31",
                    "organization_unit_id": str(uuid4())},
        )
        assert unauthorized.status_code == 403

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        audits = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_customer_lifecycle.analytics_viewed",
        ))).all()
        assert len(audits) == 1
        await context.session.execute(delete(CRMOpportunity).where(
            CRMOpportunity.tenant_id == tenant_id,
        ))
        await context.session.execute(delete(CRMProductCommerceEvent).where(
            CRMProductCommerceEvent.tenant_id == tenant_id,
            CRMProductCommerceEvent.profile_id.in_([customer_one, customer_two, lead]),
        ))
        await context.session.execute(delete(CRMProfile).where(
            CRMProfile.tenant_id == tenant_id,
            CRMProfile.id.in_([customer_one, customer_two, lead]),
        ))
        await context.session.execute(delete(TenantRecord).where(
            TenantRecord.tenant_id == tenant_id,
            TenantRecord.id.in_([customer_one, customer_two, lead]),
        ))
        await context.session.execute(delete(CRMPipeline).where(
            CRMPipeline.tenant_id == tenant_id,
            CRMPipeline.id == pipeline_id,
        ))
