from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_contact_points import (
    _environment_keyring,
    router as contact_points_router,
)
from funnel_crm.platform.contact_point_crypto import ContactPointKeyring
from funnel_crm.platform.models import (
    AuditEvent,
    CRMContactPoint,
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
    *,
    keyring: ContactPointKeyring | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    if keyring is not None:
        app.state.contact_point_keyring = keyring

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(contact_points_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_contact_point_api_encrypts_values_and_audits_only_metadata(
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
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
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
                display_name="Contact point test",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name="Contact point operator")
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
                        "crm.contact_point:view",
                        "crm.contact_point:create",
                        "crm.contact_point:update",
                    )
                ],
            ]
        )
        await context.session.flush()

    keyring = ContactPointKeyring(active_key_id="test-v1", keys={"test-v1": b"t" * 32})
    app = make_app(runtime_session_factory, identity, keyring=keyring)
    headers = {"X-Workspace-ID": str(tenant_id)}
    path = f"/api/v1/crm/profiles/{profile_id}/contact-points"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            path,
            headers=headers,
            json={"channel": "phone", "value": " +1-555-0100 ", "is_primary": True},
        )
        assert first.status_code == 201
        assert first.json()["value"] == "+1-555-0100"
        assert first.json()["verification_status"] == "unverified"
        first_id = UUID(first.json()["id"])

        second = await client.post(
            path,
            headers=headers,
            json={"channel": "phone", "value": "+1-555-0199", "is_primary": True},
        )
        assert second.status_code == 201
        second_id = UUID(second.json()["id"])

        page = await client.get(path, headers=headers)
        assert page.status_code == 200
        assert {item["value"] for item in page.json()["items"]} == {
            "+1-555-0100",
            "+1-555-0199",
        }
        primary = {item["id"]: item["is_primary"] for item in page.json()["items"]}
        assert primary[str(first_id)] is False
        assert primary[str(second_id)] is True

        updated = await client.patch(
            f"{path}/{first_id}", headers=headers, json={"is_primary": True}
        )
        assert updated.status_code == 204
        page = await client.get(path, headers=headers)
        primary = {item["id"]: item["is_primary"] for item in page.json()["items"]}
        assert primary[str(first_id)] is True
        assert primary[str(second_id)] is False

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        stored = (
            await context.session.scalars(
                select(CRMContactPoint).where(
                    CRMContactPoint.tenant_id == tenant_id,
                    CRMContactPoint.profile_id == profile_id,
                )
            )
        ).all()
        assert len(stored) == 2
        assert all(b"+1-555-" not in item.encrypted_value for item in stored)
        assert all(item.encryption_key_id == "test-v1" for item in stored)

        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_contact_point",
                )
            )
        ).all()
        assert len(events) >= 4
        assert all(
            "value" not in (event.after_state or {})
            and "encrypted_value" not in (event.after_state or {})
            for event in events
        )

        await context.session.delete(
            await context.session.get(TenantRecord, profile_id)
        )


@pytest.mark.asyncio
async def test_contact_point_read_requires_its_own_permission_and_missing_key_fails_closed(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    profile_id = uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
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
                display_name="Restricted contact point",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name="Profile only viewer")
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
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.profile:view",
                ),
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.contact_point:create",
                ),
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    path = f"/api/v1/crm/profiles/{profile_id}/contact-points"
    transport = httpx.ASGITransport(app=app)
    monkeypatch.delenv("FUNNEL_CRM_CONTACT_KEYRING", raising=False)
    _environment_keyring.cache_clear()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get(path, headers=headers)
        assert denied.status_code == 403

        monkeypatch.setenv("FUNNEL_CRM_CONTACT_KEYRING", "invalid json")
        _environment_keyring.cache_clear()
        unavailable = await client.post(
            path,
            headers=headers,
            json={"channel": "email", "value": "secret@example.test"},
        )
        assert unavailable.status_code == 503

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        await context.session.delete(
            await context.session.get(TenantRecord, profile_id)
        )
