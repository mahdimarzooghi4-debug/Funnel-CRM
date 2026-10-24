from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_profiles import router as crm_profiles_router
from funnel_crm.platform.models import (
    CRMProfile,
    OrganizationUnit,
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

    app.include_router(crm_profiles_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_profile_api_enforces_action_and_filters_rows_by_org_scope(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    branch_a_id, branch_b_id = uuid4(), uuid4()
    hidden_profile_id = uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        context.session.add_all(
            [
                OrganizationUnit(
                    id=branch_a_id,
                    tenant_id=tenant_id,
                    parent_id=root_id,
                    name="Authorized branch",
                    unit_type="unit",
                ),
                OrganizationUnit(
                    id=branch_b_id,
                    tenant_id=tenant_id,
                    parent_id=root_id,
                    name="Hidden branch",
                    unit_type="unit",
                ),
            ]
        )
        await context.session.flush()

        role = Role(tenant_id=tenant_id, name="CRM branch operator")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(
            [
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.profile:view",
                ),
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.profile:create",
                ),
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.profile:update",
                ),
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=role.id,
                    organization_unit_id=branch_a_id,
                ),
                TenantRecord(
                    id=hidden_profile_id,
                    tenant_id=tenant_id,
                    organization_unit_id=branch_b_id,
                    record_type="crm_profile",
                ),
            ]
        )
        await context.session.flush()
        context.session.add(
            CRMProfile(
                id=hidden_profile_id,
                tenant_id=tenant_id,
                organization_unit_id=branch_b_id,
                profile_kind="person",
                display_name="Hidden customer",
                lifecycle_stage="lead",
            )
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    transport = httpx.ASGITransport(app=app)
    created_id: UUID | None = None
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(branch_a_id),
                "profile_kind": "person",
                "display_name": "  Authorized customer  ",
            },
        )
        assert created.status_code == 201
        assert created.json()["display_name"] == "Authorized customer"
        created_id = UUID(created.json()["id"])

        denied_create = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(branch_b_id),
                "profile_kind": "person",
                "display_name": "Unauthorized customer",
            },
        )
        assert denied_create.status_code == 403

        page = await client.get("/api/v1/crm/profiles", headers=headers)
        assert page.status_code == 200
        assert page.json()["total"] == 1
        assert [item["id"] for item in page.json()["items"]] == [str(created_id)]

        hidden = await client.get(
            f"/api/v1/crm/profiles/{hidden_profile_id}", headers=headers
        )
        assert hidden.status_code == 404

        updated = await client.patch(
            f"/api/v1/crm/profiles/{created_id}",
            headers=headers,
            json={"lifecycle_stage": "customer"},
        )
        assert updated.status_code == 204

        fetched = await client.get(
            f"/api/v1/crm/profiles/{created_id}", headers=headers
        )
        assert fetched.status_code == 200
        assert fetched.json()["lifecycle_stage"] == "customer"

        null_update = await client.patch(
            f"/api/v1/crm/profiles/{created_id}",
            headers=headers,
            json={"display_name": None},
        )
        assert null_update.status_code == 422

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        await context.session.execute(
            delete(TenantRecord).where(TenantRecord.tenant_id == tenant_id)
        )
        await context.session.flush()
        await context.session.execute(
            delete(OrganizationUnit).where(
                OrganizationUnit.tenant_id == tenant_id,
                OrganizationUnit.id.in_([branch_a_id, branch_b_id]),
            )
        )


@pytest.mark.asyncio
async def test_membership_without_profile_grants_cannot_create_or_view(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    app = make_app(runtime_session_factory, identity)
    transport = httpx.ASGITransport(app=app)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/api/v1/crm/profiles", headers=headers)
        assert page.status_code == 200
        assert page.json()["items"] == []

        denied = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "profile_kind": "organization",
                "display_name": "No permission",
            },
        )
        assert denied.status_code == 403
