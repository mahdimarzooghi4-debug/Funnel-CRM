from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from funnel_crm.platform.product_event_worker import (
    configured_poll_seconds,
    load_worker_tenant_ids,
    process_tenant_batch,
    tenant_ids_from_registry,
)


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


def test_worker_poll_interval_is_bounded() -> None:
    assert configured_poll_seconds("2.5") == 2.5
    with pytest.raises(ValueError, match="numeric"):
        configured_poll_seconds("soon")
    with pytest.raises(ValueError, match="between"):
        configured_poll_seconds("0.1")


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
