from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_segments import router
from funnel_crm.platform.models import AuditEvent, CRMProfile, CRMProfileSegment, Role, RoleAssignment, RolePermission, TenantRecord
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
async def test_saved_segment_previews_scoped_profiles_and_records_audit(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    profile_id = uuid4()
    async with tenant_session(runtime_session_factory, requested_tenant_id=tenant_id, identity=identity) as context:
        context.session.add(
            TenantRecord(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                record_type="crm_profile",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMProfile(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_kind="person",
                display_name="Segment test profile",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name=f"Segment manager {profile_id.hex[:8]}")
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
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.profile:view"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.segment:view"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.segment:manage"),
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/crm/segments",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "New leads",
                "criteria": {"profile_kinds": ["person"], "lifecycle_stages": ["lead"]},
            },
        )
        assert created.status_code == 201
        segment_id = created.json()["id"]

        listed = await client.get("/api/v1/crm/segments", headers=headers)
        assert listed.status_code == 200
        assert any(item["id"] == segment_id for item in listed.json()["items"])

        preview = await client.get(f"/api/v1/crm/segments/{segment_id}/preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["total"] == 1
        assert preview.json()["items"][0]["id"] == str(profile_id)

        updated = await client.patch(
            f"/api/v1/crm/segments/{segment_id}",
            headers=headers,
            json={"criteria": {"profile_kinds": ["person"], "lifecycle_stages": ["customer"]}},
        )
        assert updated.status_code == 200
        preview_after_update = await client.get(
            f"/api/v1/crm/segments/{segment_id}/preview",
            headers=headers,
        )
        assert preview_after_update.status_code == 200
        assert preview_after_update.json()["total"] == 0

        deactivated = await client.post(
            f"/api/v1/crm/segments/{segment_id}/deactivate",
            headers=headers,
        )
        assert deactivated.status_code == 204
        hidden = await client.get("/api/v1/crm/segments", headers=headers)
        assert all(item["id"] != segment_id for item in hidden.json()["items"])
        inactive_preview = await client.get(
            f"/api/v1/crm/segments/{segment_id}/preview",
            headers=headers,
        )
        assert inactive_preview.status_code == 409

    async with tenant_session(runtime_session_factory, requested_tenant_id=tenant_id, identity=identity) as context:
        segment = await context.session.get(CRMProfileSegment, UUID(segment_id))
        assert segment is not None and not segment.is_active
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_profile_segment",
                    AuditEvent.target_key == segment_id,
                )
            )
        ).all()
        assert {event.action_key for event in events} == {
            "crm_profile_segment.created",
            "crm_profile_segment.updated",
            "crm_profile_segment.previewed",
            "crm_profile_segment.deactivated",
        }
        await context.session.execute(
            delete(TenantRecord).where(TenantRecord.tenant_id == tenant_id, TenantRecord.id == profile_id)
        )
        await context.session.flush()
