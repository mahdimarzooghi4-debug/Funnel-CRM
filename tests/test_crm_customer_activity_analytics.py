from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_customer_activity_analytics import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMProfile,
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
    return app


@pytest.mark.asyncio
async def test_customer_activity_analytics_compares_scoped_periods(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_a = tenant_case["workspace_a"]
    tenant_b = tenant_case["workspace_b"]
    root_a = tenant_case["root_a"]
    root_b = tenant_case["root_b"]
    identity_a = tenant_case["identity"]
    identity_b = tenant_case["identity_b"]
    assert isinstance(tenant_a, UUID)
    assert isinstance(tenant_b, UUID)
    assert isinstance(root_a, UUID)
    assert isinstance(root_b, UUID)
    assert isinstance(identity_a, AuthenticatedIdentity)
    assert isinstance(identity_b, AuthenticatedIdentity)

    profile_a, profile_a2, profile_b = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    current_time = now - timedelta(days=1)
    previous_time = now - timedelta(days=40)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_a,
        identity=identity_a,
    ) as context:
        for profile_id, name in (
            (profile_a, "Analytics customer one"),
            (profile_a2, "Analytics customer two"),
        ):
            context.session.add(
                TenantRecord(
                    id=profile_id,
                    tenant_id=tenant_a,
                    organization_unit_id=root_a,
                    record_type="crm_profile",
                )
            )
        await context.session.flush()
        context.session.add_all(
            [
                CRMProfile(
                    id=profile_a,
                    tenant_id=tenant_a,
                    organization_unit_id=root_a,
                    profile_kind="person",
                    display_name="Analytics customer one",
                    lifecycle_stage="customer",
                ),
                CRMProfile(
                    id=profile_a2,
                    tenant_id=tenant_a,
                    organization_unit_id=root_a,
                    profile_kind="person",
                    display_name="Analytics customer two",
                    lifecycle_stage="customer",
                ),
            ]
        )
        await context.session.flush()
        context.session.add_all(
            [
                CRMCustomerActivity(
                    id=uuid4(),
                    tenant_id=tenant_a,
                    profile_id=profile_a,
                    source_product="funnel.store",
                    source_event_id=uuid4(),
                    activity_type="order.completed",
                    channel="online",
                    source_record_id="order-current-1",
                    occurred_at=current_time,
                ),
                CRMCustomerActivity(
                    id=uuid4(),
                    tenant_id=tenant_a,
                    profile_id=profile_a,
                    source_product="funnel.store",
                    source_event_id=uuid4(),
                    activity_type="order.completed",
                    channel="online",
                    source_record_id="order-current-2",
                    occurred_at=current_time,
                ),
                CRMCustomerActivity(
                    id=uuid4(),
                    tenant_id=tenant_a,
                    profile_id=profile_a2,
                    source_product="funnel.visitor",
                    source_event_id=uuid4(),
                    activity_type="visit.completed",
                    channel="field",
                    source_record_id="visit-current-1",
                    occurred_at=current_time,
                ),
                CRMCustomerActivity(
                    id=uuid4(),
                    tenant_id=tenant_a,
                    profile_id=profile_a,
                    source_product="funnel.support",
                    source_event_id=uuid4(),
                    activity_type="ticket.resolved",
                    channel="phone",
                    source_record_id="ticket-old-1",
                    occurred_at=previous_time,
                ),
            ]
        )
        role = Role(tenant_id=tenant_a, name=f"Analytics reader {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(
            [
                RoleAssignment(
                    tenant_id=tenant_a,
                    membership_id=context.access.membership_id,
                    role_id=role.id,
                    organization_unit_id=root_a,
                ),
                RolePermission(
                    tenant_id=tenant_a,
                    role_id=role.id,
                    permission_key="crm.profile:view",
                ),
            ]
        )
        await context.session.flush()

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_b,
        identity=identity_b,
    ) as context:
        context.session.add(
            TenantRecord(
                id=profile_b,
                tenant_id=tenant_b,
                organization_unit_id=root_b,
                record_type="crm_profile",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMProfile(
                id=profile_b,
                tenant_id=tenant_b,
                organization_unit_id=root_b,
                profile_kind="person",
                display_name="Other tenant activity",
                lifecycle_stage="customer",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMCustomerActivity(
                id=uuid4(),
                tenant_id=tenant_b,
                profile_id=profile_b,
                source_product="funnel.store",
                source_event_id=uuid4(),
                activity_type="order.completed",
                channel="online",
                source_record_id="other-tenant-order",
                occurred_at=current_time,
            )
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity_a)
    headers = {"X-Workspace-ID": str(tenant_a)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/customer-activities/summary",
            headers=headers,
            params={"window_days": 30},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["current_activity_count"] == 3
        assert result["previous_activity_count"] == 1
        assert result["current_profiles_with_activity"] == 2
        assert result["previous_profiles_with_activity"] == 1
        assert result["activity_count_change_percent"] == 200.0
        channels = {item["key"]: item for item in result["by_channel"]}
        assert channels["online"] == {
            "key": "online",
            "current_count": 2,
            "previous_count": 0,
        }
        assert channels["field"]["current_count"] == 1
        assert channels["phone"]["previous_count"] == 1
        activity_types = {item["key"]: item for item in result["by_activity_type"]}
        assert activity_types["order.completed"]["current_count"] == 2
        assert activity_types["ticket.resolved"]["previous_count"] == 1

        hidden_scope = await client.get(
            "/api/v1/crm/analytics/customer-activities/summary",
            headers=headers,
            params={"organization_unit_id": str(root_b)},
        )
        assert hidden_scope.status_code == 404

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_a,
        identity=identity_a,
    ) as context:
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_a,
                    AuditEvent.action_key == "crm_customer_activity.analytics_viewed",
                )
            )
        ).all()
        assert len(events) == 1
        assert events[0].after_state == {
            "window_days": 30,
            "current_activity_count": 3,
            "previous_activity_count": 1,
            "current_profiles_with_activity": 2,
            "previous_profiles_with_activity": 1,
        }
