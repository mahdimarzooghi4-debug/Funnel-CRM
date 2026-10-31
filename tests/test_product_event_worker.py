from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from funnel_crm.platform.product_event_worker import (
    configured_poll_seconds,
    configured_tenant_concurrency,
    load_worker_tenant_ids,
    process_tenant_batch,
    process_tenant_batches,
    tenant_ids_from_registry,
    wait_for_poll_or_shutdown,
)



@pytest.mark.asyncio
async def test_worker_poll_wait_is_interrupted_by_shutdown() -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    assert await wait_for_poll_or_shutdown(stop_event, 60) is True


@pytest.mark.asyncio
async def test_worker_poll_wait_times_out_for_next_cycle() -> None:
    assert await wait_for_poll_or_shutdown(asyncio.Event(), 0.001) is False


def test_registry_tenant_ids_are_unique() -> None:
    tenant_id = UUID("11e54bf1-ecba-4bf6-9d02-6686d84a5d79")
    assert tenant_ids_from_registry([tenant_id]) == (tenant_id,)
    with pytest.raises(ValueError, match="duplicate"):
        tenant_ids_from_registry([tenant_id, tenant_id])


@pytest.mark.asyncio
async def test_worker_registry_tracks_new_workspaces(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    tenant_ids = await load_worker_tenant_ids(runtime_session_factory)
    assert tenant_id in tenant_ids


def test_worker_tenant_concurrency_is_bounded() -> None:
    assert configured_tenant_concurrency("6") == 6
    with pytest.raises(ValueError, match="integer"):
        configured_tenant_concurrency("many")
    with pytest.raises(ValueError, match="between"):
        configured_tenant_concurrency("33")


def test_worker_poll_interval_is_bounded() -> None:
    assert configured_poll_seconds("2.5") == 2.5
    with pytest.raises(ValueError, match="numeric"):
        configured_poll_seconds("soon")
    with pytest.raises(ValueError, match="between"):
        configured_poll_seconds("0.1")




@pytest.mark.asyncio
async def test_registered_tenants_process_concurrently_within_configured_bound() -> None:
    tenant_ids = [
        UUID("11e54bf1-ecba-4bf6-9d02-6686d84a5d79"),
        UUID("22e54bf1-ecba-4bf6-9d02-6686d84a5d79"),
        UUID("33e54bf1-ecba-4bf6-9d02-6686d84a5d79"),
        UUID("44e54bf1-ecba-4bf6-9d02-6686d84a5d79"),
    ]
    active = 0
    peak_active = 0
    visited: set[UUID] = set()

    class TrackingConsumer:
        async def process_batch(self, requested_tenant_id: UUID):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            visited.add(requested_tenant_id)
            await asyncio.sleep(0.01)
            active -= 1
            return SimpleNamespace(
                claimed=0, processed=0, failed=0, retry_scheduled=0
            )

    await process_tenant_batches(
        tenant_ids,
        concurrency=2,
        customer_consumer=TrackingConsumer(),
        commerce_consumer=TrackingConsumer(),
        legacy_commerce_consumer=TrackingConsumer(),
    )

    assert visited == set(tenant_ids)
    assert peak_active == 2
    assert active == 0

@pytest.mark.asyncio
async def test_consumer_failure_does_not_skip_other_consumer(caplog) -> None:
    tenant_id = UUID("11e54bf1-ecba-4bf6-9d02-6686d84a5d79")
    calls: list[UUID] = []

    class BrokenConsumer:
        async def process_batch(self, requested_tenant_id: UUID):
            calls.append(requested_tenant_id)
            raise RuntimeError("temporary database failure")

    class HealthyConsumer:
        async def process_batch(self, requested_tenant_id: UUID):
            calls.append(requested_tenant_id)
            return SimpleNamespace(
                claimed=2, processed=1, failed=1, retry_scheduled=1
            )

    await process_tenant_batch(
        tenant_id,
        customer_consumer=BrokenConsumer(),
        commerce_consumer=HealthyConsumer(),
        legacy_commerce_consumer=HealthyConsumer(),
    )

    assert calls == [tenant_id, tenant_id, tenant_id]
    assert "consumer=customer" in caplog.text
    assert "consumer=commerce claimed=2 processed=1 failed=1 retry_scheduled=1" in caplog.text
    assert "consumer=legacy_commerce claimed=2 processed=1 failed=1 retry_scheduled=1" in caplog.text
