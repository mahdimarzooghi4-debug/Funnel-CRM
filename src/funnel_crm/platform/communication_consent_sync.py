"""Synchronize trusted product-reported consent decisions into CRM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.platform.integration_processing import (
    ClaimedIntegrationEvent,
    LeaseLostError,
    PostgresProductEventProcessor,
)
from funnel_crm.platform.models import (
    CRMCommunicationConsentEvent,
    CRMProfile,
    ProductCustomerIdentity,
)


class CommunicationConsentPayload(BaseModel):
    """One explicit product-reported decision for a purpose and channel."""

    model_config = ConfigDict(extra="forbid")

    external_customer_id: str = Field(min_length=1, max_length=200)
    purpose_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: str = Field(pattern=r"^(email|phone|postal_address|social_handle|website)$")
    decision: str = Field(pattern=r"^(granted|withdrawn)$")
    policy_version: str = Field(min_length=1, max_length=64)

    @field_validator("external_customer_id", "policy_version")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ConsentSyncError(Exception):
    """Safe machine-readable event processing error."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class ConsentSyncBatchResult:
    claimed: int
    processed: int
    failed: int
    retry_scheduled: int


class PostgresProductConsentEventConsumer:
    """Append product-reported choices with source provenance and replay safety."""

    EVENT_TYPE = "customer.communication_consent.changed"
    CONTRACT_NAME = "crm.customer.communication_consent"
    CONTRACT_VERSION = 1

    def __init__(
        self,
        session_factory: async_sessionmaker[Any],
        *,
        payload_keyring: Any | None = None,
        lease_seconds: int = 60,
        max_attempts: int = 8,
    ) -> None:
        self._session_factory = session_factory
        self._processor = PostgresProductEventProcessor(
            session_factory,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            keyring=payload_keyring,
        )

    async def process_batch(
        self, tenant_id: UUID, *, limit: int = 10
    ) -> ConsentSyncBatchResult:
        events = await self._processor.claim(
            tenant_id,
            limit=limit,
            event_type=self.EVENT_TYPE,
            contract_name=self.CONTRACT_NAME,
            contract_version=self.CONTRACT_VERSION,
        )
        processed = failed = retry_scheduled = 0
        async with self._processor.maintain_claims(tenant_id, events):
            for event in events:
                try:
                    await self._processor.renew_lease(
                        tenant_id,
                        event.id,
                        lease_token=event.lease_token,
                    )
                except LeaseLostError:
                    continue
                try:
                    await self._process_one(event)
                except ConsentSyncError as exc:
                    result = await self._processor.fail(
                        tenant_id,
                        event.id,
                        lease_token=event.lease_token,
                        error_code=exc.code,
                        retryable=exc.retryable,
                    )
                    failed += 1
                    retry_scheduled += result.status == "received"
                except Exception:
                    result = await self._processor.fail(
                        tenant_id,
                        event.id,
                        lease_token=event.lease_token,
                        error_code="crm.consent.processing_error",
                        retryable=True,
                    )
                    failed += 1
                    retry_scheduled += result.status == "received"
                else:
                    await self._processor.complete(
                        tenant_id,
                        event.id,
                        lease_token=event.lease_token,
                    )
                    processed += 1
        return ConsentSyncBatchResult(
            claimed=len(events),
            processed=processed,
            failed=failed,
            retry_scheduled=retry_scheduled,
        )

    async def _process_one(self, event: ClaimedIntegrationEvent) -> bool:
        if (
            event.event_type != self.EVENT_TYPE
            or event.contract_name != self.CONTRACT_NAME
            or event.contract_version != self.CONTRACT_VERSION
        ):
            raise ConsentSyncError("crm.consent.unsupported_event")
        try:
            payload = CommunicationConsentPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise ConsentSyncError("crm.consent.invalid_payload") from exc

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "SELECT set_config('app.tenant_id', :tenant_id, true), "
                        "set_config('app.integration_connection_id', :connection_id, true), "
                        "set_config('app.correlation_id', :correlation_id, true)"
                    ),
                    {
                        "tenant_id": str(event.tenant_id),
                        "connection_id": str(event.connection_id),
                        "correlation_id": str(event.correlation_id),
                    },
                )
                identity = await session.scalar(
                    select(ProductCustomerIdentity).where(
                        ProductCustomerIdentity.tenant_id == event.tenant_id,
                        ProductCustomerIdentity.source_product == event.source_product,
                        ProductCustomerIdentity.external_customer_id
                        == payload.external_customer_id,
                    )
                )
                if identity is None:
                    raise ConsentSyncError(
                        "crm.consent.identity_mapping_pending",
                        retryable=True,
                    )
                profile = await session.scalar(
                    select(CRMProfile).where(
                        CRMProfile.tenant_id == event.tenant_id,
                        CRMProfile.id == identity.profile_id,
                    )
                )
                if profile is None:
                    raise ConsentSyncError(
                        "crm.consent.profile_unavailable",
                        retryable=True,
                    )

                statement = (
                    pg_insert(CRMCommunicationConsentEvent)
                    .values(
                        tenant_id=event.tenant_id,
                        profile_id=identity.profile_id,
                        purpose_key=payload.purpose_key,
                        channel=payload.channel,
                        decision=payload.decision,
                        policy_version=payload.policy_version,
                        decision_at=event.occurred_at,
                        source_product=event.source_product,
                        source_event_id=event.event_id,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            CRMCommunicationConsentEvent.tenant_id,
                            CRMCommunicationConsentEvent.source_product,
                            CRMCommunicationConsentEvent.source_event_id,
                        ],
                        index_where=CRMCommunicationConsentEvent.source_event_id.is_not(None),
                    )
                    .returning(CRMCommunicationConsentEvent.id)
                )
                consent_event_id = await session.scalar(statement)
                if consent_event_id is None:
                    existing = await session.scalar(
                        select(CRMCommunicationConsentEvent).where(
                            CRMCommunicationConsentEvent.tenant_id == event.tenant_id,
                            CRMCommunicationConsentEvent.source_product == event.source_product,
                            CRMCommunicationConsentEvent.source_event_id == event.event_id,
                        )
                    )
                    if existing is None or (
                        existing.profile_id != identity.profile_id
                        or existing.purpose_key != payload.purpose_key
                        or existing.channel != payload.channel
                        or existing.decision != payload.decision
                        or existing.policy_version != payload.policy_version
                    ):
                        raise ConsentSyncError("crm.consent.source_event_conflict")
                    return False

                return True
