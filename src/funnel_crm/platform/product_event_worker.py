"""Run tenant-scoped product event consumers as a standalone worker.

The worker discovers workspace IDs from a read-only registry.
Run one worker service per configured tenant set; the API process remains isolated
from background event processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from funnel_crm.platform.commerce_event_sync import (
    PostgresProductCommerceEventConsumer,
)
from funnel_crm.platform.contact_point_crypto import ContactPointKeyring
from funnel_crm.platform.customer_profile_sync import PostgresProductEventConsumer
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring

logger = logging.getLogger("funnel_crm.product_event_worker")


def tenant_ids_from_registry(rows: Iterable[UUID]) -> tuple[UUID, ...]:
    """Normalize tenant IDs returned by the read-only worker registry."""
    tenant_ids = tuple(rows)
    if len(set(tenant_ids)) != len(tenant_ids):
        raise ValueError("worker tenant registry contains duplicate UUIDs")
    return tenant_ids


async def load_worker_tenant_ids(
    session_factory: async_sessionmaker[Any],
) -> tuple[UUID, ...]:
    """Read tenant IDs only; event rows remain under tenant RLS."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT tenant_id FROM product_event_worker_tenants "
                "ORDER BY tenant_id"
            )
        )
        return tenant_ids_from_registry(result.scalars().all())


def configured_poll_seconds(raw: str | None = None) -> float:
    """Return a bounded delay between polling cycles."""
    value = raw if raw is not None else os.environ.get(
        "FUNNEL_CRM_EVENT_WORKER_POLL_SECONDS", "5"
    )
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError("worker poll interval must be numeric") from exc
    if not 0.25 <= seconds <= 300:
        raise ValueError("worker poll interval must be between 0.25 and 300 seconds")
    return seconds


async def process_tenant_batch(
    tenant_id: UUID,
    *,
    customer_consumer: Any,
    commerce_consumer: Any,
) -> None:
    """Run each consumer independently and report aggregate processing counts."""
    for consumer_name, consumer in (
        ("customer", customer_consumer),
        ("commerce", commerce_consumer),
    ):
        try:
            result = await consumer.process_batch(tenant_id)
        except Exception as exc:
            logger.error(
                "Product event consumer failed tenant=%s consumer=%s error_type=%s",
                tenant_id,
                consumer_name,
                type(exc).__name__,
            )
            continue
        if not result.claimed:
            continue
        log = logger.warning if result.failed else logger.info
        log(
            "Product event batch tenant=%s consumer=%s claimed=%s processed=%s failed=%s retry_scheduled=%s",
            tenant_id,
            consumer_name,
            result.claimed,
            result.processed,
            result.failed,
            result.retry_scheduled,
        )


async def run_worker(
    *,
    poll_seconds: float,
    database_url: str,
    once: bool = False,
) -> None:
    """Process CRM customer and commerce events for all registered workspaces."""
    payload_keyring = IntegrationPayloadKeyring.from_environment()
    contact_keyring = ContactPointKeyring.from_environment()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    customer_consumer = PostgresProductEventConsumer(
        session_factory,
        payload_keyring=payload_keyring,
        contact_keyring=contact_keyring,
    )
    commerce_consumer = PostgresProductCommerceEventConsumer(
        session_factory,
        payload_keyring=payload_keyring,
    )
    try:
        while True:
            try:
                tenant_ids = await load_worker_tenant_ids(session_factory)
            except Exception as exc:
                logger.error(
                    "Product event tenant registry unavailable error_type=%s",
                    type(exc).__name__,
                )
                tenant_ids = ()
            for tenant_id in tenant_ids:
                await process_tenant_batch(
                    tenant_id,
                    customer_consumer=customer_consumer,
                    commerce_consumer=commerce_consumer,
                )
            if once:
                return
            await asyncio.sleep(poll_seconds)
    finally:
        await engine.dispose()


async def main() -> None:
    """Validate deployment configuration and run the worker until stopped."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    await run_worker(
        poll_seconds=configured_poll_seconds(),
        database_url=database_url,
        once=os.environ.get("FUNNEL_CRM_EVENT_WORKER_ONCE", "").lower()
        in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
