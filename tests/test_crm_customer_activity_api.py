from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_customer_activities import router
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
async def test_customer_activity_read_is_profile_scoped_audited_and_tenant_isolated(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_a = tenant_case["workspace_a"]
    tenant_b = tenant_case["workspace_b"]
    root_a = tenant_case["root_a"]
    identity_a = tenant_case["identity"]
    identity_b = tenant_case["identity_b"]
    assert isinstance(tenant_a, UUID)
    assert isinstance(tenant_b, UUID)
    assert isinstance(root_a, UUID)
    assert isinstance(identity_a, AuthenticatedIdentity)
    assert isinstance(identity_b, AuthenticatedIdentity)

    profile_a, profile_b = uuid4(), uuid4()
    activity_id = uuid4()
    occurred_at = datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_a,
        identity=identity_a,
    ) as context:
        context.session.add(
            TenantRecord(
                id=profile_a,
                tenant_id=tenant_a,
                organization_unit_id=root_a,
                record_type="crm_profile",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMProfile(
                id=profile_a,
                tenant_id=tenant_a,
                organization_unit_id=root_a,
                profile_kind="person",
                display_name="Activity API profile",
                lifecycle_stage="customer",
            )
        )
        role = Role(tenant_id=tenant_a, name=f"Activity reader {profile_a.hex[:8]}")
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
                CRMCustomerActivity(
                    id=activity_id,
                    tenant_id=tenant_a,
                    profile_id=profile_a,
                    source_product="funnel.store",
                    source_event_id=uuid4(),
                    activity_type="order.completed",
                    channel="online",
                    source_record_id="order-a-55",
                    occurred_at=occurred_at,
                ),
            ]
        )
        await context.session.flush()

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_b,
        identity=identity_b,
    ) as context:
        root_b = tenant_case["root_b"]
        assert isinstance(root_b, UUID)
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
                display_name="Private other tenant",
                lifecycle_stage="customer",
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
            f"/api/v1/crm/profiles/{profile_a}/activities",
            headers=headers,
        )
        assert response.status_code == 200
        result = response.json()
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == str(activity_id)
        assert result["items"][0]["activity_type"] == "order.completed"
        assert result["items"][0]["source_product"] == "funnel.store"
        assert result["items"][0]["source_record_id"] == "order-a-55"
        assert datetime.fromisoformat(result["items"][0]["occurred_at"].replace("Z", "+00:00")) == occurred_at
        assert result["items"][0].get("payload") is None

        hidden = await client.get(
            f"/api/v1/crm/profiles/{profile_b}/activities",
            headers=headers,
        )
        assert hidden.status_code == 404

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_a,
        identity=identity_a,
    ) as context:
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_a,
                    AuditEvent.action_key == "crm_profile.activities_viewed",
                    AuditEvent.target_key == str(profile_a),
                )
            )
        ).all()
        assert len(events) == 1
        assert events[0].after_state == {
            "activity_count": 1,
            "total": 1,
            "limit": 50,
            "offset": 0,
        }


@pytest.mark.asyncio
async def test_offline_customer_activity_sync_is_idempotent_and_rejects_event_reuse(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID) and isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    profile_id, event_id = uuid4(), uuid4()
    occurred_at = datetime(2026, 10, 25, 8, 15, tzinfo=timezone.utc)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity,
    ) as context:
        context.session.add(TenantRecord(
            id=profile_id, tenant_id=tenant_id,
            organization_unit_id=root_id, record_type="crm_profile",
        ))
        await context.session.flush()
        context.session.add(CRMProfile(
            id=profile_id, tenant_id=tenant_id, organization_unit_id=root_id,
            profile_kind="person", display_name="Offline activity profile",
            lifecycle_stage="lead",
        ))
        role = Role(tenant_id=tenant_id, name=f"Activity writer {profile_id.hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id,
                permission_key="crm.profile:update",
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    payload = {
        "source_event_id": str(event_id),
        "activity_type": "field.visit",
        "channel": "field",
        "source_record_id": "visit-2026-10-25-1",
        "occurred_at": occurred_at.isoformat(),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        first = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/activities/sync",
            headers=headers, json=payload,
        )
        assert first.status_code == 201, first.text
        assert first.json()["duplicate"] is False
        activity_id = first.json()["activity"]["id"]
        retry = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/activities/sync",
            headers=headers, json=payload,
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["duplicate"] is True
        assert retry.json()["activity"]["id"] == activity_id
        conflict = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/activities/sync",
            headers=headers, json={**payload, "activity_type": "phone.call"},
        )
        assert conflict.status_code == 409

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity,
    ) as context:
        events = (await context.session.scalars(select(CRMCustomerActivity).where(
            CRMCustomerActivity.tenant_id == tenant_id,
            CRMCustomerActivity.source_product == "funnel-crm",
            CRMCustomerActivity.source_event_id == event_id,
        ))).all()
        assert len(events) == 1
        audits = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_profile.activity_recorded",
            AuditEvent.target_key == str(profile_id),
        ))).all()
        assert len(audits) == 1
