from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from funnel_crm.api.v1.integrations import VerifiedProductConnection, router
from funnel_crm.platform.models import AuditEvent, IntegrationEventInbox
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def create_app(connection: VerifiedProductConnection, session_factory) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def inject_verified_product(request, call_next):
        # Test-only equivalent of trusted product credential middleware.
        request.state.verified_product_connection = connection
        return await call_next(request)

    return app


def event_body(tenant_id: UUID, *, event_id: UUID | None = None) -> dict[str, object]:
    return {
        "event_id": str(event_id or uuid4()),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.store",
        "event_type": "order.created",
        "contract_name": "commerce.order",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"order_id": "order-123", "total": 1250},
    }


@pytest.mark.asyncio
async def test_postgres_event_inbox_is_durable_idempotent_and_tenant_scoped(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    event_id = uuid4()
    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.store",
        allowed_event_types=frozenset({"order.created"}),
        supported_contract_versions=frozenset({("commerce.order", 1)}),
    )
    app = create_app(connection, runtime_session_factory)
    body = event_body(tenant_id, event_id=event_id)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/api/v1/integrations/events", json=body)
        duplicate = await client.post("/api/v1/integrations/events", json=body)
        changed = {**body, "payload": {"order_id": "different-order"}}
        reused_id = await client.post("/api/v1/integrations/events", json=changed)
        cross_tenant = {
            **event_body(tenant_case["workspace_b"], event_id=uuid4()),
        }
        denied = await client.post("/api/v1/integrations/events", json=cross_tenant)

    assert first.status_code == 202
    assert first.json() == {
        "event_id": str(event_id),
        "accepted": True,
        "duplicate": False,
    }
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert reused_id.status_code == 409
    assert denied.status_code == 403

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        inbox_rows = (
            await context.session.scalars(
                IntegrationEventInbox.__table__.select().where(
                    IntegrationEventInbox.tenant_id == tenant_id,
                    IntegrationEventInbox.event_id == event_id,
                )
            )
        ).all()
        # Select ORM entities below as well to assert persisted state and payload.
        persisted = await context.session.get(IntegrationEventInbox, inbox_rows[0].id)
        assert persisted is not None
        assert persisted.processing_status == "received"
        assert persisted.payload == body["payload"]
        assert len(persisted.event_digest) == 32

        audits = (
            await context.session.scalars(
                __import__("sqlalchemy").select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action_key == "integration.event.received",
                    AuditEvent.target_key == f"funnel.store:{event_id}",
                )
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].after_state["event_type"] == "order.created"
        assert "payload" not in audits[0].after_state
