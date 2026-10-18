"""Project verified product activity events into the CRM customer timeline."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import PostgresProductEventProcessor
from funnel_crm.platform.models import CRMCustomerActivity, CRMProfile


CUSTOMER_ACTIVITY_EVENT_TYPE = "customer.activity.recorded"
CUSTOMER_ACTIVITY_CONTRACT = "funnel.customer-activity"
CUSTOMER_ACTIVITY_CONTRACT_VERSION = 1


class CustomerActivityEventPayload(BaseModel):
    """No contact details are accepted; products reference an existing CRM profile."""

    model_config = ConfigDict(extra="forbid")

    profile_id: UUID
    activity_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: Literal["online", "phone", "store", "field", "support", "campaign", "other"]
    source_record_id: str | None = Field(default=None, max_length=200)

    @field_validator("source_record_id")
    @classmethod
    def normalize_source_record_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("source_record_id cannot be blank")
        return value


class CustomerActivityProjection:
    """Idempotent projection over the existing leased product-event inbox."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        keyring: IntegrationPayloadKeyring | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._processor = PostgresProductEventProcessor(
            session_factory, keyring=keyring
        )

    async def project_event(self, tenant_id: UUID, event_id: UUID) -> str:
        claims = await self._processor.claim(
            tenant_id,
            limit=1,
            event_type=CUSTOMER_ACTIVITY_EVENT_TYPE,
            contract_name=CUSTOMER_ACTIVITY_CONTRACT,
            contract_version=CUSTOMER_ACTIVITY_CONTRACT_VERSION,
            event_id=event_id,
        )
        if not claims:
            return "not_claimed"
        claim = claims[0]

        try:
            payload = CustomerActivityEventPayload.model_validate(claim.payload)
        except ValidationError:
            failure = await self._processor.fail(
                tenant_id, claim.id, lease_token=claim.lease_token,
                error_code="customer_activity.invalid_payload", retryable=False,
            )
            return failure.status

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
                existing = await session.scalar(
                    select(CRMCustomerActivity).where(
                        CRMCustomerActivity.tenant_id == tenant_id,
                        CRMCustomerActivity.source_product == claim.source_product,
                        CRMCustomerActivity.source_event_id == claim.event_id,
                    )
                )
                if existing is not None:
                    if not self._matches(existing, claim, payload):
                        failure = await self._processor.fail(
                            tenant_id, claim.id, lease_token=claim.lease_token,
                            error_code="customer_activity.idempotency_conflict",
                            retryable=False,
                        )
                        return failure.status
                else:
                    profile_exists = await session.scalar(
                        select(CRMProfile.id).where(
                            CRMProfile.tenant_id == tenant_id,
                            CRMProfile.id == payload.profile_id,
                            CRMProfile.merged_into_profile_id.is_(None),
                        )
                    )
                    if profile_exists is None:
                        failure = await self._processor.fail(
                            tenant_id, claim.id, lease_token=claim.lease_token,
                            error_code="customer_activity.profile_unavailable",
                            retryable=True,
                        )
                        return "retrying" if failure.status == "received" else failure.status

                    statement = (
                        insert(CRMCustomerActivity)
                        .values(
                            tenant_id=tenant_id,
                            profile_id=payload.profile_id,
                            source_product=claim.source_product,
                            source_event_id=claim.event_id,
                            activity_type=payload.activity_type,
                            channel=payload.channel,
                            source_record_id=payload.source_record_id,
                            occurred_at=claim.occurred_at,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                CRMCustomerActivity.tenant_id,
                                CRMCustomerActivity.source_product,
                                CRMCustomerActivity.source_event_id,
                            ]
                        )
                    )
                    await session.execute(statement)

        await self._processor.complete(
            tenant_id, claim.id, lease_token=claim.lease_token
        )
        return "projected"

    @staticmethod
    def _matches(
        activity: CRMCustomerActivity,
        claim,
        payload: CustomerActivityEventPayload,
    ) -> bool:
        return (
            activity.profile_id == payload.profile_id
            and activity.source_product == claim.source_product
            and activity.source_event_id == claim.event_id
            and activity.activity_type == payload.activity_type
            and activity.channel == payload.channel
            and activity.source_record_id == payload.source_record_id
            and activity.occurred_at == claim.occurred_at
        )
