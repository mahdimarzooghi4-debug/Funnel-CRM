from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from funnel_crm.api.v1.integrations import router as integrations_router
from funnel_crm.api.v1.product_connections import router as connections_router
from funnel_crm.platform.integration_auth import authenticate_product_credential
from funnel_crm.platform.models import AuditEvent, ProductConnection, Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(integrations_router, prefix="/api/v1")
    app.include_router(connections_router, prefix="/api/v1")
    return app


def event(tenant_id: UUID) -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.store",
        "event_type": "order.created",
        "contract_name": "commerce.order",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"order_id": str(uuid4())},
    }


@pytest.mark.asyncio
async def test_connection_credentials_are_tenant_scoped_restricted_and_revocable(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    other_tenant = tenant_case["workspace_b"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    assert isinstance(other_tenant, UUID)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        role = Role(tenant_id=tenant_id, name=f"Integration manager {uuid4().hex[:8]}")
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
                    permission_key="crm.integration:manage",
                ),
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/integrations/connections",
            headers=headers,
            json={
                "source_product": "funnel.store",
                "allowed_event_types": ["order.created"],
                "contract_grants": [
                    {"contract_name": "commerce.order", "contract_version": 1}
                ],
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        token = created_body["credential"]
        connection_id = created_body["id"]
        assert token.startswith("fc1_")
        assert "credential_digest" not in created_body

        listed = await client.get("/api/v1/integrations/connections", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert "credential" not in listed.json()[0]
        assert token not in listed.text

        accepted = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event(tenant_id),
        )
        assert accepted.status_code == 202

        invalid = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token[:-1]}x"},
            json=event(tenant_id),
        )
        assert invalid.status_code == 401

        cross_tenant = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event(other_tenant),
        )
        assert cross_tenant.status_code == 401

        revoked = await client.post(
            f"/api/v1/integrations/connections/{connection_id}/revoke",
            headers=headers,
        )
        assert revoked.status_code == 204

        after_revoke = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event(tenant_id),
        )
        assert after_revoke.status_code == 401

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        connection = await context.session.get(ProductConnection, UUID(connection_id))
        assert connection is not None
        assert connection.revoked_at is not None
        assert len(connection.credential_digest) == 32
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "product_connection",
                    AuditEvent.target_key == connection_id,
                )
            )
        ).all()
        assert {item.action_key for item in events} == {
            "product_connection.created",
            "product_connection.revoked",
        }


@pytest.mark.asyncio
async def test_product_credential_authentication_fails_closed_without_database(
    tenant_case,
) -> None:
    connection = await authenticate_product_credential(
        None,
        tenant_id=tenant_case["workspace_a"],
        authorization="Bearer fc1_00000000-0000-4000-8000-000000000000."
        + "a" * 43,
    )
    assert connection is None
