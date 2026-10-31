"""Run tenant-scoped product event consumers as a standalone worker.

Configure FUNNEL_CRM_EVENT_WORKER_TENANT_IDS with comma-separated workspace UUIDs.
Run one worker service per configured tenant set; the API process remains isolated
from background event processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from funnel_crm.platform.commerce_event_sync import (
    PostgresProductCommerceEventConsumer,
)
from funnel_crm.platform.contact_point_crypto import ContactPointKeyring
from funnel_crm.platform.customer_profile_sync import PostgresProductEventConsumer
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring

logger = logging.getLogger("funnel_crm.product_event_worker")


def configured_tenant_ids(raw: str | None = None) -> tuple[UUID, ...]:
    """Parse explicit tenant scopes; never discover tenants through an RLS bypass."""
    value = raw if raw is not None else os.environ.get(
        "FUNNEL_CRM_EVENT_WORKER_TENANT_IDS", ""
    )
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ValueError("FUNNEL_CRM_EVENT_WORKER_TENANT_IDS must contain a workspace UUID")
    try:
        tenant_ids = tuple(UUID(part) for part in parts)
    except ValueError as exc:
        raise ValueError("worker tenant list contains an invalid UUID") from exc
    if len(set(tenant_ids)) != len(tenant_ids):
        raise ValueError("worker tenant list contains duplicate UUIDs")
    return tenant_ids


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


async def run_worker(
    *,
    tenant_ids: tuple[UUID, ...],
    poll_seconds: float,
    database_url: str,
    once: bool = False,
) -> None:
    """Process both CRM customer and commerce event contracts for configured tenants."""
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
            for tenant_id in tenant_ids:
                try:
                    customer = await customer_consumer.process_batch(tenant_id)
                    commerce = await commerce_consumer.process_batch(tenant_id)
                    if customer.claimed or commerce.claimed:
                        logger.info(
                            "Processed product events tenant=%s customer=%s commerce=%s",
                            tenant_id,
                            customer.processed,
                            commerce.processed,
                        )
                except Exception:
                    # One tenant or batch must not stop processing other configured tenants.
                    logger.exception("Product event batch failed tenant=%s", tenant_id)
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
        tenant_ids=configured_tenant_ids(),
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
