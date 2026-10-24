from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_influence import router
from funnel_crm.api.v1.crm_sales_targets import router as sales_targets_router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMMarketingCampaign,
    CRMOpportunity,
    CRMProfile,
    CRMProfileSegment,
    CRMSalesTarget,
    CRMPipeline,
    Role,
    RoleAssignment,
    RolePermission,
    TenantRecord,
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
    app.include_router(sales_targets_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_campaign_influence_reports_prior_recorded_touches_without_claiming_revenue(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    campaign_one, campaign_two, campaign_empty = uuid4(), uuid4(), uuid4()
    profile_one, profile_two, profile_without_history = uuid4(), uuid4(), uuid4()
    opportunity_one, opportunity_two, opportunity_unlinked = uuid4(), uuid4(), uuid4()
    pipeline_id, segment_id, target_id = uuid4(), uuid4(), uuid4()
    created_at = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add_all([
            TenantRecord(
                id=profile_one, tenant_id=tenant_id, organization_unit_id=root_id,
                record_type="crm_profile",
            ),
            TenantRecord(
                id=profile_two, tenant_id=tenant_id, organization_unit_id=root_id,
                record_type="crm_profile",
            ),
            TenantRecord(
                id=profile_without_history, tenant_id=tenant_id,
                organization_unit_id=root_id, record_type="crm_profile",
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMProfile(
                id=profile_one, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_kind="person", display_name="Campaign influenced buyer",
                lifecycle_stage="lead",
            ),
            CRMProfile(
                id=profile_two, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_kind="person", display_name="Later touch buyer",
                lifecycle_stage="lead",
            ),
            CRMProfile(
                id=profile_without_history, tenant_id=tenant_id,
                organization_unit_id=root_id, profile_kind="person",
                display_name="Unlinked buyer", lifecycle_stage="lead",
            ),
        ])
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Campaign influence segment {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        context.session.add(CRMPipeline(
            id=pipeline_id, tenant_id=tenant_id,
            pipeline_key=f"influence-{uuid4().hex[:8]}",
            entity_kind="opportunity", display_name="Influence pipeline",
            stages=[
                {"key": "qualified", "name": "Qualified", "position": 1,
                 "outcome_key": "open", "probability_percent": 50},
                {"key": "proposal", "name": "Proposal", "position": 2},
            ],
            is_default=False,
        ))
        await context.session.flush()
        context.session.add(CRMSalesTarget(
            id=target_id, tenant_id=tenant_id, organization_unit_id=root_id,
            pipeline_id=pipeline_id, period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31), currency="USD",
            target_amount=Decimal("20000"),
            created_by_membership_id=context.access.membership_id,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_one, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Campaign Alpha", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=campaign_two, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Campaign Beta", objective_key="acquisition",
                channel="store", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=campaign_empty, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Campaign Without Influence",
                objective_key="retention", channel="email",
                planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMOpportunity(
                id=opportunity_one, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_id=profile_one, pipeline_id=pipeline_id, name="Associated opportunity",
                stage_key="qualified", amount=Decimal("12500"), currency="USD",
                expected_close_date=date(2026, 10, 20), created_at=created_at,
            ),
            CRMOpportunity(
                id=opportunity_two, tenant_id=tenant_id, organization_unit_id=root_id,
                profile_id=profile_two, pipeline_id=pipeline_id, name="No prior touch",
                stage_key="proposal", amount=Decimal("800"), currency="EUR",
                expected_close_date=None, created_at=created_at,
            ),
            CRMOpportunity(
                id=opportunity_unlinked, tenant_id=tenant_id,
                organization_unit_id=root_id, profile_id=None,
                pipeline_id=pipeline_id, name="No linked profile",
                stage_key="qualified", amount=None, currency=None,
                expected_close_date=None, created_at=created_at,
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=profile_one,
                source_product="funnel.online", source_event_id=uuid4(),
                campaign_id=campaign_one, activity_type="campaign.clicked",
                channel="online", source_record_id="click-1",
                occurred_at=datetime(2026, 10, 14, 10, tzinfo=timezone.utc),
            ),
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=profile_one,
                source_product="funnel.store", source_event_id=uuid4(),
                campaign_id=campaign_one, activity_type="order.viewed",
                channel="store", source_record_id="visit-1",
                occurred_at=datetime(2026, 10, 14, 11, tzinfo=timezone.utc),
            ),
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=profile_one,
                source_product="funnel.online", source_event_id=uuid4(),
                campaign_id=campaign_two, activity_type="campaign.clicked",
                channel="online", source_record_id="click-2",
                occurred_at=datetime(2026, 10, 15, 11, tzinfo=timezone.utc),
            ),
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=profile_two,
                source_product="funnel.online", source_event_id=uuid4(),
                campaign_id=campaign_two, activity_type="campaign.clicked",
                channel="online", source_record_id="click-after-opportunity",
                occurred_at=datetime(2026, 10, 16, 10, tzinfo=timezone.utc),
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Influence analyst {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view",
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id, permission_key="crm.opportunity:view",
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id, permission_key="crm.sales_target:view",
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/campaign-influence",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={
                "organization_unit_id": str(root_id),
                "period_start": "2026-10-01",
                "period_end": "2026-10-31",
            },
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["revenue_attribution_applied"] is False
        assert report["total_campaign_count"] == 3
        assert [item["campaign_name"] for item in report["campaigns"]] == [
            "Campaign Alpha", "Campaign Beta", "Campaign Without Influence",
        ]
        alpha = report["campaigns"][0]
        assert alpha["associated_opportunity_count"] == 1
        assert alpha["associated_profile_count"] == 1
        assert alpha["prior_campaign_activity_count"] == 2
        assert alpha["opportunities_by_stage_currency"] == [{
            "stage_key": "qualified",
            "currency": "USD",
            "opportunity_count": 1,
            "unpriced_opportunity_count": 0,
            "opportunity_amount": "12500.000000",
        }]
        beta = report["campaigns"][1]
        assert beta["associated_opportunity_count"] == 1
        assert beta["prior_campaign_activity_count"] == 1
        assert report["campaigns"][2]["associated_opportunity_count"] == 0

        alignment = await client.get(
            "/api/v1/crm/sales-targets/campaign-influence",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"target_id": str(target_id)},
        )
        assert alignment.status_code == 200, alignment.text
        target_report = alignment.json()["items"][0]
        assert target_report["unique_campaign_influenced_opportunity_count"] == 1
        assert target_report["campaign_opportunity_association_count"] == 2
        assert target_report["multi_campaign_opportunity_count"] == 1
        assert target_report["causal_attribution_applied"] is False
        assert target_report["campaign_amounts_are_non_additive"] is True
        assert Decimal(str(target_report["unique_open_pipeline_weighted_amount"])) == Decimal("6250")
        campaign_metrics = {row["campaign_name"]: row for row in target_report["campaigns"]}
        assert Decimal(str(campaign_metrics["Campaign Alpha"]["open_pipeline_weighted_amount"])) == Decimal("6250")
        assert Decimal(str(campaign_metrics["Campaign Beta"]["open_pipeline_weighted_amount"])) == Decimal("6250")

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        events = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_campaign.influence_report_viewed",
        ))).all()
        assert len(events) == 1
        await context.session.execute(
            delete(CRMOpportunity).where(
                CRMOpportunity.tenant_id == tenant_id,
                CRMOpportunity.id.in_([
                    opportunity_one, opportunity_two, opportunity_unlinked,
                ]),
            )
        )


@pytest.mark.asyncio
async def test_campaign_influence_requires_campaign_and_opportunity_permissions(
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
        role = Role(tenant_id=tenant_id, name=f"Partial influence role {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id,
                permission_key="crm.campaign:view",
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/campaign-influence",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={
                "organization_unit_id": str(root_id),
                "period_start": "2026-10-01",
                "period_end": "2026-10-31",
            },
        )
        assert response.status_code == 403
