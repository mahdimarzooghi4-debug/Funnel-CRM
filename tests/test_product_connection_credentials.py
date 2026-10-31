from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from funnel_crm.api.v1.integrations import router as integrations_router
from funnel_crm.api.v1.integration_event_operations import router as event_operations_router
from funnel_crm.api.v1.product_connections import router as connections_router
from funnel_crm.platform.integration_auth import authenticate_product_credential
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.models import AuditEvent, IntegrationEventInbox, ProductConnection, Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.integration_payload_keyring = IntegrationPayloadKeyring(
        active_key_id="test-v1", keys={"test-v1": b"t" * 32}
    )

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(integrations_router, prefix="/api/v1")
    app.include_router(event_operations_router, prefix="/api/v1")
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
                    {"contract_name": "commerce.order", "contract_version": 1},
                    {
                        "contract_name": "crm.customer.communication_consent_changes",
                        "contract_version": 1,
                    },
                ],
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        token = created_body["credential"]
        connection_id = created_body["id"]
        initial_credential_id = created_body["credential_id"]
        assert token.startswith("fc1_")
        assert "credential_digest" not in created_body

        listed = await client.get("/api/v1/integrations/connections", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert "credential" not in listed.json()[0]
        assert token not in listed.text

        sync_health = await client.get(
            "/api/v1/integrations/connections/consent-sync",
            headers=headers,
        )
        assert sync_health.status_code == 200
        assert sync_health.json()["pending_total"] == 0
        assert sync_health.json()["behind_product_count"] == 0
        sync_item = sync_health.json()["items"][0]
        assert sync_item["connection_id"] == connection_id
        assert sync_item["source_product"] == "funnel.store"
        assert sync_item["status"] == "in_sync"
        assert sync_item["produced_sequence"] == 0
        assert sync_item["acknowledged_sequence"] == 0
        assert sync_item["pending_count"] == 0

        event_body = event(tenant_id)
        accepted = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event_body,
        )
        assert accepted.status_code == 202

        async with tenant_session(
            runtime_session_factory,
            requested_tenant_id=tenant_id,
            identity=identity,
        ) as context:
            inbox_row = await context.session.scalar(
                select(IntegrationEventInbox).where(
                    IntegrationEventInbox.tenant_id == tenant_id,
                    IntegrationEventInbox.event_id == UUID(event_body["event_id"]),
                )
            )
            assert inbox_row is not None
            inbox_row.processing_status = "failed"
            inbox_row.attempt_count = 8
            inbox_row.last_error_code = "consumer_unavailable"
            event_row_id = inbox_row.id

        failed = await client.get(
            "/api/v1/integrations/events/failed",
            headers=headers,
        )
        assert failed.status_code == 200
        assert len(failed.json()) == 1
        assert failed.json()[0]["id"] == str(event_row_id)
        assert failed.json()[0]["last_error_code"] == "consumer_unavailable"
        assert "payload" not in failed.text
        assert "order_id" not in failed.text

        health = await client.get(
            "/api/v1/integrations/events/health",
            headers=headers,
        )
        assert health.status_code == 200
        assert health.json() == [
            {
                "source_product": "funnel.store",
                "received_count": 0,
                "processing_count": 0,
                "processed_count": 0,
                "failed_count": 1,
                "oldest_unprocessed_at": None,
                "latest_received_at": health.json()[0]["latest_received_at"],
            }
        ]
        assert health.json()[0]["latest_received_at"] is not None

        retried = await client.post(
            f"/api/v1/integrations/events/{event_row_id}/retry",
            headers=headers,
        )
        assert retried.status_code == 200
        assert retried.json()["processing_status"] == "received"
        assert retried.json()["attempt_count"] == 0
        healthy_again = await client.get(
            "/api/v1/integrations/events/health",
            headers=headers,
        )
        assert healthy_again.status_code == 200
        assert healthy_again.json()[0]["received_count"] == 1
        assert healthy_again.json()[0]["failed_count"] == 0
        assert healthy_again.json()[0]["oldest_unprocessed_at"] is not None

        retry_again = await client.post(
            f"/api/v1/integrations/events/{event_row_id}/retry",
            headers=headers,
        )
        assert retry_again.status_code == 409

        rotated = await client.post(
            f"/api/v1/integrations/connections/{connection_id}/rotate-credential",
            headers=headers,
        )
        assert rotated.status_code == 200
        rotated_body = rotated.json()
        replacement_token = rotated_body["credential"]
        assert replacement_token.startswith("fc1_")
        assert replacement_token != token
        assert "credential_digest" not in rotated_body

        stale_credential = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event(tenant_id),
        )
        assert stale_credential.status_code == 202

        replacement_credential_id = rotated_body["credential_id"]
        new_credential_accepted = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {replacement_token}"},
            json=event(tenant_id),
        )
        assert new_credential_accepted.status_code == 202

        credential_list = await client.get(
            f"/api/v1/integrations/connections/{connection_id}/credentials",
            headers=headers,
        )
        assert credential_list.status_code == 200
        assert {item["credential_id"] for item in credential_list.json()} == {
            initial_credential_id,
            replacement_credential_id,
        }
        assert all("credential_digest" not in item for item in credential_list.json())

        revoke_old = await client.post(
            f"/api/v1/integrations/connections/{connection_id}/credentials/{initial_credential_id}/revoke",
            headers=headers,
        )
        assert revoke_old.status_code == 204
        stale_after_rotation = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event(tenant_id),
        )
        assert stale_after_rotation.status_code == 401

        revoke_last_active = await client.post(
            f"/api/v1/integrations/connections/{connection_id}/credentials/{replacement_credential_id}/revoke",
            headers=headers,
        )
        assert revoke_last_active.status_code == 409

        token = replacement_token
        invalid_token = token[:-1] + ("A" if token[-1] != "A" else "B")
        invalid = await client.post(
            "/api/v1/integrations/events",
            headers={"Authorization": f"Bearer {invalid_token}"},
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
            "product_connection.credential_rotated",
            "product_connection.revoked",
        }
        rotation_audit = await context.session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "product_connection.credential_rotated",
                AuditEvent.target_key == connection_id,
            )
        )
        assert rotation_audit is not None
        assert "credential_digest" not in str(rotation_audit.before_state)
        assert "credential_digest" not in str(rotation_audit.after_state)
        credential_revocation = await context.session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "product_connection.credential_revoked",
                AuditEvent.target_key == initial_credential_id,
            )
        )
        assert credential_revocation is not None
        assert credential_revocation.after_state == {
            "revoked": True,
            "connection_id": connection_id,
        }
        retry_audit = await context.session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "integration.event.requeued",
                AuditEvent.target_key == str(event_row_id),
            )
        )
        assert retry_audit is not None
        assert retry_audit.before_state == {
            "processing_status": "failed",
            "attempt_count": 8,
            "last_error_code": "consumer_unavailable",
        }
        assert retry_audit.after_state == {
            "processing_status": "received",
            "attempt_count": 0,
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
