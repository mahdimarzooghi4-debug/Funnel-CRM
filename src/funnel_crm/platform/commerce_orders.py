"""Consume paid-order and refund events into the tenant-scoped commerce fact ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import (
    ClaimedIntegrationEvent,
    LeaseLostError,
    PostgresProductEventProcessor,
)
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMProductCommerceEvent,
    CRMProfile,
    IntegrationEventInbox,
    OrganizationUnit,
    WorkspaceMembership,
)


class CommerceOrderEventPayload(BaseModel):
    """Version one payload; amounts are source-reported and currency-specific."""

    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    campaign_id: UUID | None = None
    profile_id: UUID | None = None
    seller_membership_id: UUID | None = None
    order_reference: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("order_reference")
    @classmethod
    def clean_order_reference(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("order_reference must not be blank")
        return result


class CommerceOrderEventError(ValueError):
    """An event does not meet the commerce contract or CRM scope."""


@dataclass(frozen=True)
class CommerceOrderBatchResult:
    claimed: int
    processed: int
    duplicate: int
    failed: int
    retry_scheduled: int


class PostgresCommerceOrderEventConsumer:
    """Atomically store one order fact and complete its inbox lease.

    The source event ID is the idempotency key. Refunds are separate positive
    source amounts and are never silently netted against paid-order amounts.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        payload_keyring: IntegrationPayloadKeyring | None = None,
    ):
        self._session_factory = session_factory
        self._processor = PostgresProductEventProcessor(
            session_factory, keyring=payload_keyring
        )

    async def process_batch(
        self, tenant_id: UUID, *, limit: int = 10
    ) -> CommerceOrderBatchResult:
        claims = await self._processor.claim(
            tenant_id,
            limit=limit,
            contract_name="commerce.order",
            contract_version=1,
        )
        processed = duplicate = failed = retry_scheduled = 0
        async with self._processor.maintain_claims(tenant_id, claims):
            for claim in claims:
                try:
                    await self._processor.renew_lease(
                        tenant_id,
                        claim.id,
                        lease_token=claim.lease_token,
                    )
                except LeaseLostError:
                    continue
                try:
                    inserted = await self.consume(claim)
                except (CommerceOrderEventError, LeaseLostError):
                    failed += 1
                except Exception:
                    try:
                        result = await self._processor.fail(
                            tenant_id,
                            claim.id,
                            lease_token=claim.lease_token,
                            error_code="commerce_order.processing_error",
                            retryable=True,
                        )
                    except LeaseLostError:
                        result = None
                    failed += 1
                    retry_scheduled += result is not None and result.status == "received"
                else:
                    processed += 1
                    duplicate += not inserted
        return CommerceOrderBatchResult(
            claimed=len(claims),
            processed=processed,
            duplicate=duplicate,
            failed=failed,
            retry_scheduled=retry_scheduled,
        )

    async def consume(self, claim: ClaimedIntegrationEvent) -> bool:
        try:
            return await self._consume_validated(claim)
        except (ValidationError, ValueError) as exc:
            if isinstance(exc, LeaseLostError):
                raise
            try:
                await self._processor.fail(
                    claim.tenant_id,
                    claim.id,
                    lease_token=claim.lease_token,
                    error_code="commerce_order.invalid_event",
                    retryable=False,
                )
            except LeaseLostError:
                raise
            raise CommerceOrderEventError(
                "Commerce event failed contract or CRM scope validation"
            ) from exc

    async def _consume_validated(self, claim: ClaimedIntegrationEvent) -> bool:
        kind_by_type = {
            "commerce.order.paid": "paid",
            "commerce.order.refunded": "refunded",
        }
        event_kind = kind_by_type.get(claim.event_type)
        if (
            claim.contract_name != "commerce.order"
            or claim.contract_version != 1
            or event_kind is None
        ):
            raise CommerceOrderEventError("Unsupported commerce event contract")
        payload = CommerceOrderEventPayload.model_validate(claim.payload)

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(claim.tenant_id)},
                )
                inbox = await session.scalar(
                    select(IntegrationEventInbox)
                    .where(
                        IntegrationEventInbox.tenant_id == claim.tenant_id,
                        IntegrationEventInbox.id == claim.id,
                        IntegrationEventInbox.processing_status == "processing",
                        IntegrationEventInbox.lease_token == claim.lease_token,
                        IntegrationEventInbox.event_id == claim.event_id,
                        IntegrationEventInbox.source_product == claim.source_product,
                    )
                    .with_for_update()
                )
                if inbox is None:
                    raise LeaseLostError("event lease is no longer current")
                if (
                    inbox.contract_name != "commerce.order"
                    or inbox.contract_version != 1
                    or inbox.event_type != claim.event_type
                ):
                    raise CommerceOrderEventError("Claim does not match stored event contract")

                unit_exists = await session.scalar(
                    select(OrganizationUnit.id).where(
                        OrganizationUnit.tenant_id == claim.tenant_id,
                        OrganizationUnit.id == payload.organization_unit_id,
                    )
                )
                if unit_exists is None:
                    raise CommerceOrderEventError("Organization scope is not in the event tenant")

                if payload.profile_id is not None:
                    profile = await session.scalar(
                        select(CRMProfile).where(
                            CRMProfile.tenant_id == claim.tenant_id,
                            CRMProfile.id == payload.profile_id,
                        )
                    )
                    if profile is None or profile.organization_unit_id != payload.organization_unit_id:
                        raise CommerceOrderEventError("Customer profile is outside the event organization")

                if payload.campaign_id is not None:
                    campaign = await session.scalar(
                        select(CRMMarketingCampaign.id).where(
                            CRMMarketingCampaign.tenant_id == claim.tenant_id,
                            CRMMarketingCampaign.organization_unit_id == payload.organization_unit_id,
                            CRMMarketingCampaign.id == payload.campaign_id,
                        )
                    )
                    if campaign is None:
                        raise CommerceOrderEventError("Campaign is outside the event organization")

                if payload.seller_membership_id is not None:
                    seller_exists = await session.scalar(
                        select(WorkspaceMembership.id).where(
                            WorkspaceMembership.tenant_id == claim.tenant_id,
                            WorkspaceMembership.id == payload.seller_membership_id,
                        )
                    )
                    if seller_exists is None:
                        raise CommerceOrderEventError("Seller membership is outside the event tenant")

                values = {
                    "id": uuid4(),
                    "tenant_id": claim.tenant_id,
                    "organization_unit_id": payload.organization_unit_id,
                    "campaign_id": payload.campaign_id,
                    "profile_id": payload.profile_id,
                    "seller_membership_id": payload.seller_membership_id,
                    "source_product": claim.source_product,
                    "source_event_id": claim.event_id,
                    "event_type": claim.event_type,
                    "order_reference": payload.order_reference,
                    "event_kind": event_kind,
                    "amount": payload.amount,
                    "currency": payload.currency,
                    "occurred_at": inbox.occurred_at,
                }
                inserted_id = await session.scalar(
                    insert(CRMProductCommerceEvent)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=[
                            CRMProductCommerceEvent.tenant_id,
                            CRMProductCommerceEvent.source_product,
                            CRMProductCommerceEvent.source_event_id,
                        ]
                    )
                    .returning(CRMProductCommerceEvent.id)
                )
                if inserted_id is None:
                    existing = await session.scalar(
                        select(CRMProductCommerceEvent).where(
                            CRMProductCommerceEvent.tenant_id == claim.tenant_id,
                            CRMProductCommerceEvent.source_product == claim.source_product,
                            CRMProductCommerceEvent.source_event_id == claim.event_id,
                        )
                    )
                    if existing is None or any(
                        getattr(existing, key) != value
                        for key, value in values.items()
                        if key != "id"
                    ):
                        raise CommerceOrderEventError(
                            "Source event ID conflicts with a different commerce fact"
                        )

                inbox.processing_status = "processed"
                inbox.processed_at = datetime.now(timezone.utc)
                inbox.lease_token = None
                inbox.lease_until = None
                inbox.last_error_code = None
                await session.flush()
                return inserted_id is not None
