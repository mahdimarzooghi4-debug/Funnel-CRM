"""Tenant-scoped, retryable processing lifecycle for product event inbox rows.

Delivery is at-least-once: consumers must use the event ID idempotently when
performing effects outside the database.
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.platform.integration_payload_crypto import (
    IntegrationPayloadCryptoError,
    IntegrationPayloadKeyring,
)
from funnel_crm.platform.models import IntegrationEventInbox

logger = logging.getLogger(__name__)

_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class LeaseLostError(Exception):
    """The event is no longer owned by this processing attempt."""


@dataclass(frozen=True)
class ClaimedIntegrationEvent:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    event_id: UUID
    source_product: str
    event_type: str
    contract_name: str
    contract_version: int
    correlation_id: UUID
    occurred_at: datetime
    payload: dict[str, Any]
    attempt_count: int
    lease_token: UUID
    lease_until: datetime


@dataclass(frozen=True)
class EventFailureResult:
    status: str
    attempt_count: int
    available_at: datetime | None


class PostgresProductEventProcessor:
    """Claim, acknowledge, and retry events within one explicit tenant scope."""

    def __init__(
        self,
        session_factory: async_sessionmaker[Any],
        *,
        lease_seconds: int = 60,
        max_attempts: int = 8,
        base_retry_seconds: int = 5,
        max_retry_seconds: int = 3600,
        keyring: IntegrationPayloadKeyring | None = None,
    ) -> None:
        if not 1 <= lease_seconds <= 86_400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        if not 1 <= max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if base_retry_seconds < 0 or max_retry_seconds < base_retry_seconds:
            raise ValueError("retry delay bounds are invalid")
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._base_retry_seconds = base_retry_seconds
        self._max_retry_seconds = max_retry_seconds
        self._keyring = keyring


    @asynccontextmanager
    async def maintain_claims(self, tenant_id: UUID, claims):
        """Keep every claim in a sequential batch leased while it is being handled."""
        if not claims:
            yield
            return
        heartbeat = asyncio.create_task(
            self._heartbeat_claims(tenant_id, claims),
            name="product-event-lease-heartbeat",
        )
        try:
            yield
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat_claims(self, tenant_id: UUID, claims) -> None:
        interval = max(0.25, self._lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            for claim in claims:
                try:
                    await self.renew_lease(
                        tenant_id,
                        claim.id,
                        lease_token=claim.lease_token,
                    )
                except LeaseLostError:
                    continue
                except Exception as exc:
                    logger.warning(
                        "Product event lease heartbeat failed tenant=%s event=%s error_type=%s",
                        tenant_id,
                        claim.id,
                        type(exc).__name__,
                    )

    async def renew_lease(
        self, tenant_id: UUID, event_row_id: UUID, *, lease_token: UUID
    ) -> datetime:
        """Extend a live lease only while this claim still owns the event."""
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=self._lease_seconds)
        async with self._session_factory() as session:
            async with session.begin():
                await self._set_tenant(session, tenant_id)
                result = await session.execute(
                    update(IntegrationEventInbox)
                    .where(
                        IntegrationEventInbox.tenant_id == tenant_id,
                        IntegrationEventInbox.id == event_row_id,
                        IntegrationEventInbox.processing_status == "processing",
                        IntegrationEventInbox.lease_token == lease_token,
                        IntegrationEventInbox.lease_until > now,
                    )
                    .values(lease_until=lease_until)
                    .returning(IntegrationEventInbox.id)
                )
                if result.scalar_one_or_none() is None:
                    raise LeaseLostError("event lease is no longer current")
        return lease_until

    async def claim(
        self,
        tenant_id: UUID,
        *,
        limit: int = 10,
        event_type: str | None = None,
        contract_name: str | None = None,
        contract_version: int | None = None,
    ) -> list[ClaimedIntegrationEvent]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        now = datetime.now(timezone.utc)
        claimed: list[ClaimedIntegrationEvent] = []

        async with self._session_factory() as session:
            async with session.begin():
                await self._set_tenant(session, tenant_id)
                # A process may die after its final claim. Once that lease expires,
                # move the row to terminal failure instead of leaving it stuck.
                await session.execute(
                    update(IntegrationEventInbox)
                    .where(
                        IntegrationEventInbox.tenant_id == tenant_id,
                        IntegrationEventInbox.processing_status == "processing",
                        or_(
                            IntegrationEventInbox.lease_until.is_(None),
                            IntegrationEventInbox.lease_until <= now,
                        ),
                        IntegrationEventInbox.attempt_count >= self._max_attempts,
                    )
                    .values(
                        processing_status="failed",
                        lease_token=None,
                        lease_until=None,
                        last_error_code="lease_expired_max_attempts",
                    )
                )

                eligible = or_(
                    and_(
                        IntegrationEventInbox.processing_status == "received",
                        IntegrationEventInbox.available_at <= now,
                        IntegrationEventInbox.attempt_count < self._max_attempts,
                    ),
                    and_(
                        IntegrationEventInbox.processing_status == "processing",
                        or_(
                            IntegrationEventInbox.lease_until.is_(None),
                            IntegrationEventInbox.lease_until <= now,
                        ),
                        IntegrationEventInbox.attempt_count < self._max_attempts,
                    ),
                )
                claim_filters = [
                    IntegrationEventInbox.tenant_id == tenant_id,
                    eligible,
                ]
                if event_type is not None:
                    claim_filters.append(
                        IntegrationEventInbox.event_type == event_type
                    )
                if contract_name is not None:
                    claim_filters.append(
                        IntegrationEventInbox.contract_name == contract_name
                    )
                if contract_version is not None:
                    claim_filters.append(
                        IntegrationEventInbox.contract_version == contract_version
                    )
                rows = (
                    await session.scalars(
                        select(IntegrationEventInbox)
                        .where(*claim_filters)
                        .order_by(
                            IntegrationEventInbox.available_at,
                            IntegrationEventInbox.received_at,
                            IntegrationEventInbox.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()

                for row in rows:
                    payload = row.payload
                    if row.encrypted_payload is not None and row.payload_key_id is not None:
                        keyring = self._keyring
                        if keyring is None:
                            keyring = IntegrationPayloadKeyring.from_environment()
                        try:
                            payload = keyring.decrypt(
                                tenant_id=row.tenant_id,
                                event_id=row.event_id,
                                source_product=row.source_product,
                                event_type=row.event_type,
                                contract_name=row.contract_name,
                                contract_version=row.contract_version,
                                key_id=row.payload_key_id,
                                ciphertext=row.encrypted_payload,
                            )
                        except IntegrationPayloadCryptoError as exc:
                            raise ValueError(
                                "claimed integration payload cannot be safely decrypted"
                            ) from exc
                    token = uuid4()
                    lease_until = now + timedelta(seconds=self._lease_seconds)
                    row.processing_status = "processing"
                    row.attempt_count += 1
                    row.lease_token = token
                    row.lease_until = lease_until
                    claimed.append(
                        ClaimedIntegrationEvent(
                            id=row.id,
                            tenant_id=row.tenant_id,
                            connection_id=row.connection_id,
                            event_id=row.event_id,
                            source_product=row.source_product,
                            event_type=row.event_type,
                            contract_name=row.contract_name,
                            contract_version=row.contract_version,
                            correlation_id=row.correlation_id,
                            occurred_at=row.occurred_at,
                            payload=payload,
                            attempt_count=row.attempt_count,
                            lease_token=token,
                            lease_until=lease_until,
                        )
                    )
        return claimed

    async def complete(
        self, tenant_id: UUID, event_row_id: UUID, *, lease_token: UUID
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                await self._set_tenant(session, tenant_id)
                result = await session.execute(
                    update(IntegrationEventInbox)
                    .where(
                        IntegrationEventInbox.tenant_id == tenant_id,
                        IntegrationEventInbox.id == event_row_id,
                        IntegrationEventInbox.processing_status == "processing",
                        IntegrationEventInbox.lease_token == lease_token,
                    )
                    .values(
                        processing_status="processed",
                        processed_at=now,
                        lease_token=None,
                        lease_until=None,
                        last_error_code=None,
                    )
                    .returning(IntegrationEventInbox.id)
                )
                if result.scalar_one_or_none() is None:
                    raise LeaseLostError("event lease is no longer current")

    async def fail(
        self,
        tenant_id: UUID,
        event_row_id: UUID,
        *,
        lease_token: UUID,
        error_code: str,
        retryable: bool = True,
    ) -> EventFailureResult:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a short machine-readable code")
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                await self._set_tenant(session, tenant_id)
                row = await session.scalar(
                    select(IntegrationEventInbox)
                    .where(
                        IntegrationEventInbox.tenant_id == tenant_id,
                        IntegrationEventInbox.id == event_row_id,
                        IntegrationEventInbox.processing_status == "processing",
                        IntegrationEventInbox.lease_token == lease_token,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise LeaseLostError("event lease is no longer current")

                should_retry = retryable and row.attempt_count < self._max_attempts
                if should_retry:
                    exponent = min(max(row.attempt_count - 1, 0), 20)
                    delay = min(
                        self._base_retry_seconds * (2**exponent),
                        self._max_retry_seconds,
                    )
                    row.processing_status = "received"
                    row.available_at = now + timedelta(seconds=delay)
                    available_at: datetime | None = row.available_at
                    result_status = "received"
                else:
                    row.processing_status = "failed"
                    available_at = None
                    result_status = "failed"
                row.last_error_code = error_code
                row.lease_token = None
                row.lease_until = None
                return EventFailureResult(
                    status=result_status,
                    attempt_count=row.attempt_count,
                    available_at=available_at,
                )

    async def _set_tenant(self, session, tenant_id: UUID) -> None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
