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
async def test_profile_csv_export_is_scoped_audited_and_formula_safe(
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
                display_name="=1+1",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name=f"CSV exporter {profile_id.hex[:8]}")
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
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.profile:export"),
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        exported = await client.get("/api/v1/crm/profiles/export.csv", headers=headers)
        assert exported.status_code == 200
        assert "text/csv" in exported.headers["content-type"]
        assert exported.headers["cache-control"] == "no-store"
        lines = exported.text.splitlines()
        assert lines[0] == "profile_id,organization_unit_id,profile_kind,display_name,lifecycle_stage,created_at,updated_at"
        assert str(profile_id) in lines[1]
        assert "'=1+1" in lines[1]
        assert "email" not in exported.text
        assert "contact" not in exported.text

    async with tenant_session(runtime_session_factory, requested_tenant_id=tenant_id, identity=identity) as context:
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action_key == "crm_profile.exported",
                    AuditEvent.target_key == "csv",
                )
            )
        ).all()
        assert len(events) == 1
        assert events[0].after_state == {"format": "csv", "rows": 1, "offset": 0, "limit": 5000}
        await context.session.execute(
            delete(TenantRecord).where(TenantRecord.tenant_id == tenant_id, TenantRecord.id == profile_id)
        )
        await context.session.flush()
