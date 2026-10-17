from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_communication_consent import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommunicationConsentEvent,
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
async def test_consent_ledger_is_explicit_append_only_and_latest_withdrawal_denies(
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
                display_name="Consent test",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name="Consent manager")
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
                        "crm.communication_consent:view",
                        "crm.communication_consent:record",
                    )
                ],
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    path = f"/api/v1/crm/profiles/{profile_id}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unknown = await client.get(
            f"{path}/communication-eligibility",
            headers=headers,
            params={"purpose_key": "product_updates", "channel": "email"},
        )
        assert unknown.status_code == 200
        assert unknown.json()["allowed"] is False
        assert unknown.json()["decision"] is None

        granted = await client.post(
            f"{path}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "product_updates",
                "channel": "email",
                "decision": "granted",
                "policy_version": "2026-10-v1",
            },
        )
        assert granted.status_code == 201
        assert granted.json()["decision"] == "granted"

        allowed = await client.get(
            f"{path}/communication-eligibility",
            headers=headers,
            params={"purpose_key": "product_updates", "channel": "email"},
        )
        assert allowed.json()["allowed"] is True

        withdrawn = await client.post(
            f"{path}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "product_updates",
                "channel": "email",
                "decision": "withdrawn",
                "policy_version": "2026-10-v2",
            },
        )
        assert withdrawn.status_code == 201

        denied = await client.get(
            f"{path}/communication-eligibility",
            headers=headers,
            params={"purpose_key": "product_updates", "channel": "email"},
        )
        assert denied.status_code == 200
        assert denied.json()["allowed"] is False
        assert denied.json()["decision"] == "withdrawn"

        invalid = await client.post(
            f"{path}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "Product Updates",
                "channel": "email",
                "decision": "granted",
                "policy_version": "v3",
            },
        )
        assert invalid.status_code == 422

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        events = (
            await context.session.scalars(
                select(CRMCommunicationConsentEvent)
                .where(
                    CRMCommunicationConsentEvent.tenant_id == tenant_id,
                    CRMCommunicationConsentEvent.profile_id == profile_id,
                )
                .order_by(CRMCommunicationConsentEvent.id)
            )
        ).all()
        assert [event.decision for event in events] == ["granted", "withdrawn"]
        with pytest.raises(DBAPIError):
            async with context.session.begin_nested():
                events[-1].decision = "granted"
                await context.session.flush()

        audits = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_communication_consent_event",
                )
            )
        ).all()
        assert {event.action_key for event in audits} == {
            "crm.communication_consent.granted",
            "crm.communication_consent.withdrawn",
        }
        assert all("value" not in (event.after_state or {}) for event in audits)
        await context.session.delete(await context.session.get(TenantRecord, profile_id))


@pytest.mark.asyncio
async def test_consent_history_requires_dedicated_permission(
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
                display_name="Restricted consent",
                lifecycle_stage="lead",
            )
        )
        role = Role(tenant_id=tenant_id, name="Profile viewer")
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
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/crm/profiles/{profile_id}/communication-consents",
            headers={"X-Workspace-ID": str(tenant_id)},
        )
        assert response.status_code == 403

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        await context.session.delete(await context.session.get(TenantRecord, profile_id))
