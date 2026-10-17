import asyncio
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from funnel_crm.api.v1.integrations import (
    EventReceipt,
    ProductEventEnvelope,
    ProductEventSink,
    VerifiedProductConnection,
    router,
)


class MemoryInbox(ProductEventSink):
    """Test-only deterministic inbox that models durable idempotency semantics."""

    def __init__(self) -> None:
        self.events: dict[tuple[str, str, str], EventReceipt] = {}

    async def accept(
        self, connection: VerifiedProductConnection, event: ProductEventEnvelope
    ) -> EventReceipt:
        key = (str(connection.tenant_id), connection.source_product, str(event.event_id))
        existing = self.events.get(key)
        if existing is not None:
            return EventReceipt(event_id=existing.event_id, duplicate=True)
        receipt = EventReceipt(event_id=event.event_id, duplicate=False)
        self.events[key] = receipt
        return receipt


def make_connection(
    *,
    tenant_id=None,
    allowed_event_types=frozenset({"order.created"}),
    versions=frozenset({("commerce.order", 1)}),
) -> VerifiedProductConnection:
    return VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        source_product="funnel.store",
        allowed_event_types=allowed_event_types,
        supported_contract_versions=versions,
    )


def make_event(connection: VerifiedProductConnection, **overrides) -> dict[str, object]:
    value: dict[str, object] = {
        "event_id": str(uuid4()),
        "tenant_id": str(connection.tenant_id),
        "source_product": connection.source_product,
        "event_type": "order.created",
        "contract_name": "commerce.order",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"order_id": str(uuid4())},
    }
    value.update(overrides)
    return value


def create_test_app(
    connection: VerifiedProductConnection | None,
    *,
    sink: MemoryInbox | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if sink is not None:
        app.state.product_event_sink = sink

    if connection is not None:
        @app.middleware("http")
        async def inject_test_principal(request, call_next):
            # This represents trusted auth middleware only inside this test app.
            request.state.verified_product_connection = connection
            return await call_next(request)

    return app


@pytest.mark.asyncio
async def test_integration_api_fails_closed_without_verified_identity() -> None:
    app = create_test_app(None, sink=MemoryInbox())
    connection = make_connection()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/integrations/events", json=make_event(connection)
        )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        {"tenant_id": str(uuid4())},
        {"source_product": "other.product"},
        {"event_type": "customer.export"},
        {"contract_version": 2},
    ],
)
async def test_integration_api_denies_claims_outside_connection_grant(claim) -> None:
    connection = make_connection()
    app = create_test_app(connection, sink=MemoryInbox())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/integrations/events", json=make_event(connection, **claim)
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_integration_api_does_not_claim_success_without_durable_sink() -> None:
    connection = make_connection()
    app = create_test_app(connection)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/integrations/events", json=make_event(connection)
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_product_event_api_concurrency_smoke() -> None:
    """Exercise concurrent ASGI requests; this is a regression smoke, not a capacity claim."""
    connection = make_connection()
    sink = MemoryInbox()
    app = create_test_app(connection, sink=sink)
    request_count = 256
    concurrency = 32
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=15.0,
    ) as client:
        async def send_one() -> httpx.Response:
            async with semaphore:
                return await client.post(
                    "/api/v1/integrations/events",
                    json=make_event(connection),
                )

        started = perf_counter()
        responses = await asyncio.gather(*(send_one() for _ in range(request_count)))
        elapsed = perf_counter() - started

    assert all(response.status_code == 202 for response in responses)
    assert len(sink.events) == request_count
    assert elapsed < 15.0
    print(
        f"event API smoke: {request_count} requests, concurrency={concurrency}, "
        f"elapsed={elapsed:.3f}s, throughput={request_count / elapsed:.1f} req/s"
    )
