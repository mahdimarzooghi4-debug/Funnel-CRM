from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_custom_field_definitions import router as definitions_router
from funnel_crm.api.v1.crm_profiles import router as profiles_router
from funnel_crm.platform.models import (
    CRMCustomFieldDefinition,
    CRMProfileCustomFieldValue,
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

    app.include_router(profiles_router, prefix="/api/v1")
    app.include_router(definitions_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_managed_required_custom_fields_are_enforced_atomically_on_profile_create(
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
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        role = Role(tenant_id=tenant_id, name="Custom field manager")
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
                *[
                    RolePermission(
                        tenant_id=tenant_id,
                        role_id=role.id,
                        permission_key=permission,
                    )
                    for permission in (
                        "crm.custom_field:manage",
                        "crm.custom_field:view",
                        "crm.custom_field:update",
                        "crm.profile:create",
                    )
                ],
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    transport = httpx.ASGITransport(app=app)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created_definition = await client.post(
            "/api/v1/crm/custom-fields",
            headers=headers,
            json={
                "entity_kind": "person",
                "field_key": "loyalty_tier",
                "display_name": "Loyalty tier",
                "value_type": "choice",
                "options": ["silver", "gold"],
                "is_required": True,
            },
        )
        assert created_definition.status_code == 201
        field_id = UUID(created_definition.json()["id"])

        missing = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "profile_kind": "person",
                "display_name": "Missing tier",
            },
        )
        assert missing.status_code == 422
        assert missing.json()["detail"]["field_keys"] == ["loyalty_tier"]

        invalid = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "profile_kind": "person",
                "display_name": "Invalid tier",
                "custom_fields": {"loyalty_tier": "platinum"},
            },
        )
        assert invalid.status_code == 422

        created_profile = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "profile_kind": "person",
                "display_name": "Gold customer",
                "custom_fields": {"loyalty_tier": "gold"},
            },
        )
        assert created_profile.status_code == 201
        profile_id = UUID(created_profile.json()["id"])

        async with tenant_session(
            runtime_session_factory,
            requested_tenant_id=tenant_id,
            identity=identity,
        ) as context:
            stored = await context.session.scalar(
                select(CRMProfileCustomFieldValue).where(
                    CRMProfileCustomFieldValue.tenant_id == tenant_id,
                    CRMProfileCustomFieldValue.profile_id == profile_id,
                    CRMProfileCustomFieldValue.field_definition_id == field_id,
                )
            )
            assert stored is not None
            assert stored.value == "gold"

        invalid_options = await client.patch(
            "/api/v1/crm/custom-fields/loyalty_tier?entity_kind=person",
            headers=headers,
            json={"options": ["silver"]},
        )
        assert invalid_options.status_code == 409

        deactivated = await client.delete(
            "/api/v1/crm/custom-fields/loyalty_tier?entity_kind=person",
            headers=headers,
        )
        assert deactivated.status_code == 204

        definitions = await client.get("/api/v1/crm/custom-fields", headers=headers)
        assert definitions.status_code == 200
        assert len(definitions.json()) == 1
        assert definitions.json()[0]["is_active"] is False

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        profile = await context.session.scalar(
            select(CRMCustomFieldDefinition).where(
                CRMCustomFieldDefinition.tenant_id == tenant_id,
                CRMCustomFieldDefinition.field_key == "loyalty_tier",
            )
        )
        assert profile is not None
