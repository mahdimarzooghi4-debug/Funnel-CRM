from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaigns import router
from funnel_crm.api.v1.crm_campaign_readiness import router as readiness_router
from funnel_crm.api.v1.crm_communication_consent import router as consent_router
from funnel_crm.platform.models import (
    CRMContactPoint,
    CRMMarketingCampaign,
    CRMProfile,
    CRMProfileSegment,
    TenantRecord,
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
    app.include_router(readiness_router, prefix="/api/v1")
    app.include_router(consent_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_campaign_planning_lifecycle_is_scoped_and_never_sends(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        segment = CRMProfileSegment(
            id=uuid4(),
            tenant_id=tenant_id,
            organization_unit_id=root_id,
            name=f"Campaign audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]},
            is_active=True,
        )
        context.session.add(segment)
        profile_id = uuid4()
        context.session.add(TenantRecord(
            id=profile_id, tenant_id=tenant_id,
            organization_unit_id=root_id, record_type="crm_profile",
        ))
        await context.session.flush()
        context.session.add(CRMProfile(
            id=profile_id, tenant_id=tenant_id, organization_unit_id=root_id,
            profile_kind="person", display_name="Campaign readiness profile",
            lifecycle_stage="lead",
        ))
        await context.session.flush()
        context.session.add(CRMContactPoint(
            id=uuid4(), tenant_id=tenant_id, profile_id=profile_id,
            channel="email", encrypted_value=b"x" * 29,
            encryption_key_id="test-key", fingerprint_key_id=None,
            match_fingerprint=None, verification_status="verified", is_primary=True,
        ))
        await context.session.flush()
        role = Role(tenant_id=tenant_id, name=f"Campaign manager {uuid4().hex[:8]}")
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
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.campaign:manage",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.segment:view",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.profile:view",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.contact_point:view",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.communication_consent:view",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.communication_consent:record",
                ),
            ]
        )
        await context.session.flush()
        segment_id = segment.id

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        starts = datetime.now(timezone.utc) + timedelta(days=3)
        ends = starts + timedelta(days=7)
        created = await client.post(
            "/api/v1/crm/campaigns",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "segment_id": str(segment_id),
                "name": "Spring offer",
                "objective_key": "repeat_purchase",
                "communication_purpose_key": "repeat_purchase",
                "channel": "email",
                "planned_budget_amount": "1200.50",
                "planned_budget_currency": "USD",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]
        assert created.json()["status"] == "draft"
        assert created.json()["communication_purpose_key"] == "repeat_purchase"
        assert created.json()["planned_budget_amount"] == "1200.50"
        assert created.json()["planned_budget_currency"] == "USD"

        readiness = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/readiness",
            headers=headers,
        )
        assert readiness.status_code == 200, readiness.text
        readiness_result = readiness.json()
        assert readiness_result["communication_purpose_key"] == "repeat_purchase"
        assert readiness_result["launch_readiness"] == "needs_attention"
        eligibility_check = next(
            item for item in readiness_result["checks"]
            if item["key"] == "channel_eligibility"
        )
        assert eligibility_check["status"] == "missing"
        assert eligibility_check["count"] == 0

        portfolio = await client.get(
            "/api/v1/crm/campaigns/readiness-portfolio",
            headers=headers,
            params={"limit": 1, "offset": 0},
        )
        assert portfolio.status_code == 200, portfolio.text
        portfolio_result = portfolio.json()
        assert portfolio_result["total_draft_campaigns"] == 1
        assert portfolio_result["has_more"] is False
        assert portfolio_result["ready_for_manager_review_count"] == 0
        assert portfolio_result["needs_attention_count"] == 1
        assert portfolio_result["items"][0]["campaign_id"] == campaign_id
        assert portfolio_result["attention_by_check"]["channel_eligibility"] == 1

        marketing_consent = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "marketing",
                "channel": "email",
                "decision": "granted",
                "policy_version": "v1",
            },
        )
        assert marketing_consent.status_code == 201, marketing_consent.text
        wrong_purpose_readiness = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/readiness",
            headers=headers,
        )
        wrong_check = next(
            item for item in wrong_purpose_readiness.json()["checks"]
            if item["key"] == "channel_eligibility"
        )
        assert wrong_check["count"] == 0

        campaign_consent = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "repeat_purchase",
                "channel": "email",
                "decision": "granted",
                "policy_version": "v1",
            },
        )
        assert campaign_consent.status_code == 201, campaign_consent.text
        eligible_readiness = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/readiness",
            headers=headers,
        )
        eligible_check = next(
            item for item in eligible_readiness.json()["checks"]
            if item["key"] == "channel_eligibility"
        )
        assert eligible_check["status"] == "complete"
        assert eligible_check["count"] == 1

        listed = await client.get("/api/v1/crm/campaigns", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == campaign_id

        partial_budget = await client.patch(
            f"/api/v1/crm/campaigns/{campaign_id}",
            headers=headers,
            json={"planned_budget_amount": "900.00"},
        )
        assert partial_budget.status_code == 422

        updated = await client.patch(
            f"/api/v1/crm/campaigns/{campaign_id}",
            headers=headers,
            json={"channel": "store", "ends_at": (ends + timedelta(days=1)).isoformat(), "planned_budget_amount": "1000.00", "planned_budget_currency": "USD"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["channel"] == "store"
        assert updated.json()["planned_budget_amount"] == "1000.00"

        unsupported_readiness = await client.get(
            f"/api/v1/crm/campaigns/{campaign_id}/readiness",
            headers=headers,
        )
        assert unsupported_readiness.status_code == 200, unsupported_readiness.text
        unsupported_check = next(
            item for item in unsupported_readiness.json()["checks"]
            if item["key"] == "channel_eligibility"
        )
        assert unsupported_check["status"] == "unsupported"
        assert unsupported_check["count"] is None

        archived = await client.post(
            f"/api/v1/crm/campaigns/{campaign_id}/archive", headers=headers
        )
        assert archived.status_code == 204

        archived_list = await client.get(
            "/api/v1/crm/campaigns?status=archived", headers=headers
        )
        assert archived_list.status_code == 200
        assert archived_list.json()["total"] == 1

        cannot_edit = await client.patch(
            f"/api/v1/crm/campaigns/{campaign_id}",
            headers=headers,
            json={"name": "Changed after archive"},
        )
        assert cannot_edit.status_code == 409

        no_sender = await client.post(
            f"/api/v1/crm/campaigns/{campaign_id}/send", headers=headers
        )
        assert no_sender.status_code == 404

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        stored = await context.session.scalar(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.id == UUID(campaign_id),
            )
        )
        assert stored is not None
        assert stored.status == "archived"
        assert stored.channel == "store"


@pytest.mark.asyncio
async def test_campaign_portfolio_reports_only_proven_same_segment_schedule_conflicts(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    first_segment_id, other_segment_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(days=10)
    window_end = window_start + timedelta(days=14)
    campaigns = [
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=first_segment_id, name="Email A", objective_key="retention",
            channel="email", planned_budget_amount=Decimal("100.50"), planned_budget_currency="USD",
            starts_at=window_start + timedelta(hours=2),
            ends_at=window_start + timedelta(days=4), status="draft",
        ),
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=first_segment_id, name="Phone B", objective_key="retention",
            channel="phone", planned_budget_amount=Decimal("200"), planned_budget_currency="USD",
            starts_at=window_start + timedelta(days=2),
            ends_at=window_start + timedelta(days=6), status="draft",
        ),
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=other_segment_id, name="Store C", objective_key="awareness",
            channel="store", planned_budget_amount=Decimal("300"), planned_budget_currency="EUR",
            starts_at=window_start + timedelta(days=2),
            ends_at=window_start + timedelta(days=6), status="draft",
        ),
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=first_segment_id, name="Outside window", objective_key="retention",
            channel="email", planned_budget_amount=Decimal("50"), planned_budget_currency="USD",
            starts_at=window_end + timedelta(days=2),
            ends_at=window_end + timedelta(days=4), status="draft",
        ),
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=first_segment_id, name="Unscheduled", objective_key="retention",
            channel="email", starts_at=None, ends_at=None, status="draft",
        ),
    ]
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add_all(
            [
                CRMProfileSegment(
                    id=first_segment_id, tenant_id=tenant_id,
                    organization_unit_id=root_id, name=f"Portfolio A {uuid4().hex[:8]}",
                    criteria={"profile_kinds": ["person"]}, is_active=True,
                ),
                CRMProfileSegment(
                    id=other_segment_id, tenant_id=tenant_id,
                    organization_unit_id=root_id, name=f"Portfolio B {uuid4().hex[:8]}",
                    criteria={"profile_kinds": ["organization"]}, is_active=True,
                ),
            ]
        )
        role = Role(tenant_id=tenant_id, name=f"Portfolio viewer {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(campaigns)
        context.session.add_all(
            [
                RoleAssignment(
                    tenant_id=tenant_id, membership_id=context.access.membership_id,
                    role_id=role.id, organization_unit_id=root_id,
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
            "/api/v1/crm/campaigns/portfolio",
            headers=headers,
            params={
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total_draft_campaigns"] == 5
    assert result["scheduled_campaigns_in_window"] == 3
    assert result["unscheduled_campaigns"] == 1
    assert result["unbudgeted_draft_campaigns"] == 1
    assert result["draft_budget_by_currency"] == {"EUR": "300.000000", "USD": "350.500000"}
    assert result["exact_same_segment_conflict_pairs"] == 1
    assert result["overlap_basis"] == "same_segment_id_and_overlapping_schedule"
    assert result["truncated"] is False
    item_by_name = {item["name"]: item for item in result["items"]}
    assert item_by_name["Email A"]["overlapping_campaign_ids"] == [
        item_by_name["Phone B"]["id"]
    ]
    assert item_by_name["Store C"]["overlapping_campaign_ids"] == []
