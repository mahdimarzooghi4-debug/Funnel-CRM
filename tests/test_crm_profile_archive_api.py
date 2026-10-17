from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_profiles import router
from funnel_crm.platform.models import AuditEvent, CRMProfile, Role, RoleAssignment, RolePermission, TenantRecord
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
async def test_profile_archive_restore_is_scoped_and_audited(
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
                display_name="Archived test profile",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name=f"Archive manager {profile_id.hex[:8]}")
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
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.profile:archive"),
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        archive = await client.post(f"/api/v1/crm/profiles/{profile_id}/archive", headers=headers)
        assert archive.status_code == 204
        repeated = await client.post(f"/api/v1/crm/profiles/{profile_id}/archive", headers=headers)
        assert repeated.status_code == 204

        default_page = await client.get("/api/v1/crm/profiles", headers=headers)
        assert default_page.status_code == 200
        assert str(profile_id) not in {item["id"] for item in default_page.json()["items"]}

        archived_page = await client.get(
            "/api/v1/crm/profiles?include_archived=true",
            headers=headers,
        )
        assert archived_page.status_code == 200
        assert str(profile_id) in {item["id"] for item in archived_page.json()["items"]}
        assert next(item for item in archived_page.json()["items"] if item["id"] == str(profile_id))["archived_at"]

        restore = await client.post(f"/api/v1/crm/profiles/{profile_id}/restore", headers=headers)
        assert restore.status_code == 204
        restored_page = await client.get("/api/v1/crm/profiles", headers=headers)
        assert restored_page.status_code == 200
        assert str(profile_id) in {item["id"] for item in restored_page.json()["items"]}

    async with tenant_session(runtime_session_factory, requested_tenant_id=tenant_id, identity=identity) as context:
        profile = await context.session.get(CRMProfile, profile_id)
        assert profile is not None and profile.archived_at is None
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_profile_archive",
                    AuditEvent.target_key == str(profile_id),
                ).order_by(AuditEvent.id)
            )
        ).all()
        assert [event.action_key for event in events] == ["crm_profile.archived", "crm_profile.restored"]
        await context.session.execute(
            delete(TenantRecord).where(TenantRecord.tenant_id == tenant_id, TenantRecord.id == profile_id)
        )
        await context.session.flush()
