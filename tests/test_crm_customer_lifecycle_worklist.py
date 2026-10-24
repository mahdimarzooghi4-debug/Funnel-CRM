from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_customer_lifecycle_worklist import router
from funnel_crm.platform.models import (
    CRMCustomerActivity,
    CRMProfile,
    Role,
    RoleAssignment,
    RolePermission,
    TenantRecord,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(
    session_factory: async_sessionmaker[AsyncSession], identity: AuthenticatedIdentity
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
async def test_lifecycle_follow_up_candidates_use_selected_rule_and_recorded_evidence(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    stale_profile_id, recent_profile_id, no_activity_profile_id = uuid4(), uuid4(), uuid4()
    profile_ids = (stale_profile_id, recent_profile_id, no_activity_profile_id)
    tenant_case["lifecycle_cleanup_profile_ids"] = profile_ids
    reference = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add_all([
            TenantRecord(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                record_type="crm_profile",
            )
            for profile_id in profile_ids
        ])
        await context.session.flush()
        context.session.add_all([
            CRMProfile(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_kind="person",
                display_name=name,
                lifecycle_stage="customer",
            )
            for profile_id, name in (
                (stale_profile_id, "Lifecycle stale customer"),
                (recent_profile_id, "Lifecycle recent customer"),
                (no_activity_profile_id, "Lifecycle untracked customer"),
            )
        ])
        await context.session.flush()
        context.session.add_all([
            CRMCustomerActivity(
                id=uuid4(),
                tenant_id=tenant_id,
                profile_id=stale_profile_id,
                source_product="funnel.store",
                source_event_id=uuid4(),
                campaign_id=None,
                activity_type="order.completed",
                channel="store",
                occurred_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
            ),
            CRMCustomerActivity(
                id=uuid4(),
                tenant_id=tenant_id,
                profile_id=recent_profile_id,
                source_product="funnel.web",
                source_event_id=uuid4(),
                campaign_id=None,
                activity_type="form.submitted",
                channel="online",
                occurred_at=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Lifecycle reviewer {uuid4().hex[:8]}")
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
                tenant_id=tenant_id,
                role_id=role.id,
                permission_key="crm.profile:view",
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        params = {
            "as_of": reference.isoformat(),
            "inactive_for_days": 30,
            "lifecycle_stage": "customer",
            "limit": 1,
        }
        response = await client.get(
            "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates",
            headers={"X-Workspace-ID": str(tenant_id)},
            params=params,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 2
        assert page["has_more"] is True
        assert page["contact_action_executed"] is False
        assert page["causal_risk_inferred"] is False
        first = page["candidates"][0]
        assert first["profile_id"] == str(no_activity_profile_id)
        assert first["latest_recorded_activity_at"] is None
        assert first["recorded_activity_count"] == 0
        assert "No linked activity" in first["reason"]

        second_response = await client.get(
            "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={**params, "offset": 1},
        )
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()["candidates"][0]
        assert second["profile_id"] == str(stale_profile_id)
        assert second["recorded_activity_count"] == 1
        assert second["days_since_recorded_activity"] == 49
        assert second["reason"].startswith("Latest linked activity")

        unauthorized = await client.get(
            "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={**params, "organization_unit_id": str(uuid4())},
        )
        assert unauthorized.status_code == 403

        naive_timestamp = await client.get(
            "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"as_of": "2026-10-20T12:00:00", "inactive_for_days": 30},
        )
        assert naive_timestamp.status_code == 422
