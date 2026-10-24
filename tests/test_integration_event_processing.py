from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from funnel_crm.api.v1.integrations import VerifiedProductConnection, router
from funnel_crm.platform.integration_processing import (
    LeaseLostError,
    PostgresProductEventProcessor,
)
from funnel_crm.platform.models import IntegrationEventInbox
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def create_event_app(connection: VerifiedProductConnection, session_factory) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def inject_verified_product(request, call_next):
        request.state.verified_product_connection = connection
        return await call_next(request)

    return app


async def send_event(client: httpx.AsyncClient, tenant_id: UUID) -> UUID:
    event_id = uuid4()
    response = await client.post(
        "/api/v1/integrations/events",
        json={
            "event_id": str(event_id),
            "tenant_id": str(tenant_id),
            "source_product": "funnel.store",
            "event_type": "order.created",
            "contract_name": "commerce.order",
            "contract_version": 1,
            "correlation_id": str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"order_id": str(uuid4())},
        },
    )
    assert response.status_code == 202
    return event_id


@pytest.mark.asyncio
async def test_processor_claims_with_tenant_scope_and_completes_once(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.store",
        allowed_event_types=frozenset({"order.created"}),
        supported_contract_versions=frozenset({("commerce.order", 1)}),
    )
    app = create_event_app(connection, runtime_session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        event_id = await send_event(client, tenant_id)

    processor = PostgresProductEventProcessor(runtime_session_factory)
    claims = await processor.claim(tenant_id, limit=10)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.event_id == event_id
    assert claim.attempt_count == 1

    # A live lease prevents another worker from receiving this event.
    assert await processor.claim(tenant_id) == []
    assert await processor.claim(tenant_case["workspace_b"]) == []

    await processor.complete(tenant_id, claim.id, lease_token=claim.lease_token)
    with pytest.raises(LeaseLostError):
        await processor.complete(tenant_id, claim.id, lease_token=claim.lease_token)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        row = await context.session.scalar(
            select(IntegrationEventInbox).where(
                IntegrationEventInbox.tenant_id == tenant_id,
                IntegrationEventInbox.event_id == event_id,
            )
        )
        assert row is not None
        assert row.processing_status == "processed"
        assert row.attempt_count == 1
        assert row.processed_at is not None
        assert row.lease_token is None


@pytest.mark.asyncio
async def test_processor_recovers_expired_lease_and_bounds_retries(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.store",
        allowed_event_types=frozenset({"order.created"}),
        supported_contract_versions=frozenset({("commerce.order", 1)}),
    )
    app = create_event_app(connection, runtime_session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        event_id = await send_event(client, tenant_id)

    processor = PostgresProductEventProcessor(
        runtime_session_factory,
        max_attempts=2,
        base_retry_seconds=0,
        max_retry_seconds=0,
    )
    first = (await processor.claim(tenant_id))[0]
    # Simulate a worker crash after claiming; the next worker must acquire a
    # fresh lease after expiry and invalidate the old token.
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        await context.session.execute(
            update(IntegrationEventInbox)
            .where(IntegrationEventInbox.id == first.id)
            .values(lease_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        )

    second = (await processor.claim(tenant_id))[0]
    assert second.attempt_count == 2
    assert second.lease_token != first.lease_token
    with pytest.raises(LeaseLostError):
        await processor.complete(tenant_id, first.id, lease_token=first.lease_token)

    terminal = await processor.fail(
        tenant_id,
        second.id,
        lease_token=second.lease_token,
        error_code="consumer.invalid_record",
        retryable=True,
    )
    assert terminal.status == "failed"
    assert terminal.attempt_count == 2
    with pytest.raises(ValueError):
        await processor.fail(
            tenant_id,
            second.id,
            lease_token=second.lease_token,
            error_code="raw exception text is not allowed",
        )

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        row = await context.session.scalar(
            select(IntegrationEventInbox).where(
                IntegrationEventInbox.tenant_id == tenant_id,
                IntegrationEventInbox.event_id == event_id,
            )
        )
        assert row is not None
        assert row.processing_status == "failed"
        assert row.attempt_count == 2
        assert row.last_error_code == "consumer.invalid_record"
        assert row.lease_token is None
