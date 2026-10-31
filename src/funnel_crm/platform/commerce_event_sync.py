"""Synchronize authoritative product order events into CRM commerce facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import (
    LeaseLostError,
    ClaimedIntegrationEvent,
    PostgresProductEventProcessor,
)
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMProfile,
    CRMProductCommerceEvent,
    ProductCustomerIdentity,
)


class CommerceOrderPayload(BaseModel):
    """Minimal order facts needed for marketing attribution and revenue reporting."""

    model_config = ConfigDict(extra="forbid")

    external_customer_id: str = Field(min_length=1, max_length=200)
    order_reference: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    campaign_id: UUID | None = None

    @field_validator("external_customer_id", "order_reference")
    @classmethod
    def strip_identifiers(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value


class CommerceSyncError(Exception):
    """Safe machine-readable event processing error."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class CommerceSyncBatchResult:
    claimed: int
    processed: int
    failed: int
    retry_scheduled: int


class PostgresProductCommerceEventConsumer:
    """Consume paid/refunded order events from the durable product inbox."""

    EVENT_KINDS = {
        "commerce.order.paid": "paid",
        "commerce.order.refunded": "refunded",
    }

    def __init__(
        self,
        session_factory: async_sessionmaker[Any],
        *,
        payload_keyring: IntegrationPayloadKeyring | None = None,
        lease_seconds: int = 60,
        max_attempts: int = 8,
    ) -> None:
        self._processor = PostgresProductEventProcessor(
            session_factory,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            keyring=payload_keyring,
        )
        self._session_factory = session_factory

    async def process_batch(
        self, tenant_id: UUID, *, limit: int = 10
    ) -> CommerceSyncBatchResult:
        events: list[ClaimedIntegrationEvent] = []
        for event_type in self.EVENT_KINDS:
            events.extend(await self._processor.claim(
                tenant_id, limit=limit, event_type=event_type,
                contract_name="crm.commerce.order", contract_version=1,
            ))
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
                except CommerceSyncError as exc:
                    result = await self._processor.fail(
                        tenant_id, event.id, lease_token=event.lease_token,
                        error_code=exc.code, retryable=exc.retryable,
                    )
                    failed += 1
                    retry_scheduled += result.status == "received"
                except Exception:
                    result = await self._processor.fail(
                        tenant_id, event.id, lease_token=event.lease_token,
                        error_code="crm.commerce.processing_error", retryable=True,
                    )
                    failed += 1
                    retry_scheduled += result.status == "received"
                else:
                    await self._processor.complete(
                        tenant_id, event.id, lease_token=event.lease_token
                    )
                    processed += 1
        return CommerceSyncBatchResult(
            claimed=len(events), processed=processed, failed=failed,
            retry_scheduled=retry_scheduled,
        )

    async def _process_one(self, event: ClaimedIntegrationEvent) -> None:
        kind = self.EVENT_KINDS.get(event.event_type)
        if kind is None or event.contract_name != "crm.commerce.order" or event.contract_version != 1:
            raise CommerceSyncError("crm.commerce.unsupported_event")
        try:
            payload = CommerceOrderPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise CommerceSyncError("crm.commerce.invalid_payload") from exc

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
                    select(ProductCustomerIdentity)
                    .where(
                        ProductCustomerIdentity.tenant_id == event.tenant_id,
                        ProductCustomerIdentity.source_product == event.source_product,
                        ProductCustomerIdentity.external_customer_id == payload.external_customer_id,
                    )
                    .with_for_update()
                )
                if identity is None:
                    raise CommerceSyncError(
                        "crm.commerce.profile_mapping_pending", retryable=True
                    )
                profile = await session.scalar(
                    select(CRMProfile)
                    .where(
                        CRMProfile.tenant_id == event.tenant_id,
                        CRMProfile.id == identity.profile_id,
                    )
                    .with_for_update()
                )
                if profile is None or profile.archived_at is not None:
                    raise CommerceSyncError("crm.commerce.profile_unavailable")
                if profile.merged_into_profile_id is not None:
                    raise CommerceSyncError("crm.commerce.profile_merged")

                if payload.campaign_id is not None:
                    campaign = await session.scalar(
                        select(CRMMarketingCampaign).where(
                            CRMMarketingCampaign.tenant_id == event.tenant_id,
                            CRMMarketingCampaign.id == payload.campaign_id,
                            CRMMarketingCampaign.organization_unit_id == profile.organization_unit_id,
                        )
                    )
                    if campaign is None:
                        raise CommerceSyncError("crm.commerce.campaign_unavailable")

                commerce_event = CRMProductCommerceEvent(
                    id=uuid4(),
                    tenant_id=event.tenant_id,
                    organization_unit_id=profile.organization_unit_id,
                    campaign_id=payload.campaign_id,
                    profile_id=profile.id,
                    seller_membership_id=None,
                    source_product=event.source_product,
                    source_event_id=event.event_id,
                    event_type=event.event_type,
                    order_reference=payload.order_reference,
                    event_kind=kind,
                    amount=payload.amount,
                    currency=payload.currency,
                    occurred_at=event.occurred_at,
                )
                inserted_id = await session.scalar(
                    pg_insert(CRMProductCommerceEvent)
                    .values(
                        id=commerce_event.id,
                        tenant_id=commerce_event.tenant_id,
                        organization_unit_id=commerce_event.organization_unit_id,
                        campaign_id=commerce_event.campaign_id,
                        profile_id=commerce_event.profile_id,
                        seller_membership_id=commerce_event.seller_membership_id,
                        source_product=commerce_event.source_product,
                        source_event_id=commerce_event.source_event_id,
                        event_type=commerce_event.event_type,
                        order_reference=commerce_event.order_reference,
                        event_kind=commerce_event.event_kind,
                        amount=commerce_event.amount,
                        currency=commerce_event.currency,
                        occurred_at=commerce_event.occurred_at,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "tenant_id", "source_product", "source_event_id"
                        ]
                    )
                    .returning(CRMProductCommerceEvent.id)
                )
                if inserted_id is None:
                    prior = await session.scalar(
                        select(CRMProductCommerceEvent)
                        .where(
                            CRMProductCommerceEvent.tenant_id == event.tenant_id,
                            CRMProductCommerceEvent.source_product == event.source_product,
                            CRMProductCommerceEvent.source_event_id == event.event_id,
                        )
                        .with_for_update()
                    )
                    same_fact = prior is not None and (
                        prior.organization_unit_id == profile.organization_unit_id
                        and prior.campaign_id == payload.campaign_id
                        and prior.profile_id == profile.id
                        and prior.event_type == event.event_type
                        and prior.order_reference == payload.order_reference
                        and prior.event_kind == kind
                        and prior.amount == payload.amount
                        and prior.currency == payload.currency
                        and prior.occurred_at == event.occurred_at
                    )
                    if not same_fact:
                        raise CommerceSyncError(
                            "crm.commerce.source_event_conflict"
                        )
                    return

                session.add(
                    AuditEvent(
                        tenant_id=event.tenant_id,
                        actor_kind="system",
                        actor_identity_id=None,
                        actor_membership_id=None,
                        action_key="integration.commerce.order_recorded",
                        target_type="crm_product_commerce_event",
                        target_key=str(commerce_event.id),
                        organization_unit_id=profile.organization_unit_id,
                        before_state=None,
                        after_state={
                            "source_product": event.source_product,
                            "source_event_id": str(event.event_id),
                            "event_kind": kind,
                            "currency": payload.currency,
                            "campaign_id": str(payload.campaign_id) if payload.campaign_id else None,
                        },
                        correlation_id=event.correlation_id,
                    )
                )
