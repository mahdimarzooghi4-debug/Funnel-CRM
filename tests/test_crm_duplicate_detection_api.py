from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_contact_points import router as contact_points_router
from funnel_crm.api.v1.crm_duplicates import router as duplicate_router
from funnel_crm.platform.contact_point_crypto import ContactPointKeyring
from funnel_crm.platform.models import (
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
    app.state.contact_point_keyring = ContactPointKeyring(
        active_key_id="test-v1",
        keys={"test-v1": b"m" * 32},
    )

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(contact_points_router, prefix="/api/v1")
    app.include_router(duplicate_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_duplicate_candidates_match_without_exposing_contact_values(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    profile_ids = [uuid4(), uuid4(), uuid4()]
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        for profile_id, name in zip(profile_ids, ("Primary", "Possible match", "Other")):
            context.session.add(
                TenantRecord(
                    id=profile_id,
                    tenant_id=tenant_id,
                    organization_unit_id=root_id,
                    record_type="crm_profile",
                )
            )
        await context.session.flush()
        for profile_id, name in zip(profile_ids, ("Primary", "Possible match", "Other")):
            context.session.add(
                CRMProfile(
                    id=profile_id,
                    tenant_id=tenant_id,
                    organization_unit_id=root_id,
                    profile_kind="person",
                    display_name=name,
                    lifecycle_stage="lead",
                )
            )
        role = Role(tenant_id=tenant_id, name="Duplicate reviewer")
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
                        "crm.profile:view",
                        "crm.profile:review_duplicates",
                        "crm.contact_point:create",
                    )
                ],
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    transport = httpx.ASGITransport(app=app)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for profile_id, phone in zip(
            profile_ids,
            ("+1-555-0100", "+1-555-0100", "+1-555-0199"),
        ):
            response = await client.post(
                f"/api/v1/crm/profiles/{profile_id}/contact-points",
                headers=headers,
                json={"channel": "phone", "value": phone},
            )
            assert response.status_code == 201

        response = await client.get(
            f"/api/v1/crm/profiles/{profile_ids[0]}/possible-duplicates",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == [
            {
                "profile_id": str(profile_ids[1]),
                "display_name": "Possible match",
                "matching_channels": ["phone"],
            }
        ]
        assert "+1-555-" not in response.text

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        await context.session.delete(await context.session.get(TenantRecord, profile_ids[0]))
        await context.session.delete(await context.session.get(TenantRecord, profile_ids[1]))
        await context.session.delete(await context.session.get(TenantRecord, profile_ids[2]))
