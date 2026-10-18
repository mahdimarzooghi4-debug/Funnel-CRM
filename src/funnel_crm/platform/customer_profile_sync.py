"""Versioned product-to-CRM customer profile synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.platform.contact_point_crypto import (
    ContactPointCryptoError,
    ContactPointKeyring,
)
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import (
    ClaimedIntegrationEvent,
    PostgresProductEventProcessor,
)
from funnel_crm.platform.models import (
    AuditEvent,
    CRMContactPoint,
    CRMCustomerActivity,
    CRMCustomFieldDefinition,
    CRMProfile,
    OrganizationUnit,
    ProductCustomerIdentity,
    TenantRecord,
    Workspace,
)


class CustomerContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(pattern=r"^(email|phone|postal_address|social_handle|website)$")
    value: str = Field(min_length=1, max_length=1000)

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value


class CustomerProfileUpsertPayload(BaseModel):
    """Snapshot of one source product customer; contains no consent assertion."""

    model_config = ConfigDict(extra="forbid")

    external_customer_id: str = Field(min_length=1, max_length=200)
    profile_kind: str = Field(pattern=r"^(person|organization)$")
    display_name: str = Field(min_length=1, max_length=240)
    contacts: list[CustomerContactInput] = Field(default_factory=list, max_length=20)

    @field_validator("external_customer_id", "display_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value


class CustomerActivityPayload(BaseModel):
    """Structured customer activity; intentionally excludes free-text and consent."""

    model_config = ConfigDict(extra="forbid")

    external_customer_id: str = Field(min_length=1, max_length=200)
    activity_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: str = Field(
        pattern=r"^(online|phone|store|field|support|campaign|other)$"
    )
    source_record_id: str | None = Field(default=None, min_length=1, max_length=200)
    campaign_id: UUID | None = None

    @field_validator("external_customer_id", "source_record_id")
    @classmethod
    def strip_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value


class CustomerSyncError(Exception):
    """A safe, machine-readable integration error; never contains payload data."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class CustomerSyncBatchResult:
    claimed: int
    processed: int
    failed: int
    retry_scheduled: int


class PostgresProductEventConsumer:
    """Consume customer upsert events into tenant-scoped CRM profiles."""

    def __init__(
        self,
        session_factory: async_sessionmaker[Any],
        *,
        payload_keyring: IntegrationPayloadKeyring | None = None,
        contact_keyring: ContactPointKeyring | None = None,
        lease_seconds: int = 60,
        max_attempts: int = 8,
    ) -> None:
        self._session_factory = session_factory
        self._payload_keyring = payload_keyring
        self._contact_keyring = contact_keyring
        self._processor = PostgresProductEventProcessor(
            session_factory,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            keyring=payload_keyring,
        )

    async def process_batch(
        self, tenant_id: UUID, *, limit: int = 10
    ) -> CustomerSyncBatchResult:
        upsert_events = await self._processor.claim(
            tenant_id,
            limit=limit,
            event_type="customer.upserted",
            contract_name="crm.customer",
            contract_version=1,
        )
        activity_events = await self._processor.claim(
            tenant_id,
            limit=limit,
            event_type="customer.activity.recorded",
            contract_name="crm.customer.activity",
            contract_version=1,
        )
        events = [*upsert_events, *activity_events]
        processed = failed = retry_scheduled = 0
        for event in events:
            try:
                await self._process_one(event)
            except CustomerSyncError as exc:
                result = await self._processor.fail(
                    tenant_id,
                    event.id,
                    lease_token=event.lease_token,
                    error_code=exc.code,
                    retryable=exc.retryable,
                )
                failed += 1
                retry_scheduled += result.status == "received"
            except ContactPointCryptoError:
                result = await self._processor.fail(
                    tenant_id,
                    event.id,
                    lease_token=event.lease_token,
                    error_code="crm.customer.contact_encryption_unavailable",
                    retryable=True,
                )
                failed += 1
                retry_scheduled += result.status == "received"
            except Exception:
                result = await self._processor.fail(
                    tenant_id,
                    event.id,
                    lease_token=event.lease_token,
                    error_code="crm.customer.processing_error",
                    retryable=True,
                )
                failed += 1
                retry_scheduled += result.status == "received"
            else:
                await self._processor.complete(
                    tenant_id, event.id, lease_token=event.lease_token
                )
                processed += 1
        return CustomerSyncBatchResult(
            claimed=len(events),
            processed=processed,
            failed=failed,
            retry_scheduled=retry_scheduled,
        )

    async def _process_one(self, event: ClaimedIntegrationEvent) -> None:
        if (
            event.event_type == "customer.activity.recorded"
            and event.contract_name == "crm.customer.activity"
            and event.contract_version == 1
        ):
            await self._process_activity(event)
            return
        if (
            event.event_type != "customer.upserted"
            or event.contract_name != "crm.customer"
            or event.contract_version != 1
        ):
            raise CustomerSyncError("crm.customer.unsupported_event")
        try:
            payload = CustomerProfileUpsertPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise CustomerSyncError("crm.customer.invalid_payload") from exc
        if self._contact_keyring is None:
            raise ContactPointCryptoError(
                "contact-point encryption is not configured"
            )

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
                workspace = await session.scalar(
                    select(Workspace).where(Workspace.id == event.tenant_id)
                )
                if workspace is None:
                    raise CustomerSyncError("crm.customer.tenant_unavailable")
                organization = await session.scalar(
                    select(OrganizationUnit).where(
                        OrganizationUnit.tenant_id == event.tenant_id,
                        OrganizationUnit.id == workspace.root_organization_id,
                    )
                )
                if organization is None or organization.unit_type != "root":
                    raise CustomerSyncError("crm.customer.root_scope_unavailable")

                required_custom_field = await session.scalar(
                    select(CRMCustomFieldDefinition.id)
                    .where(
                        CRMCustomFieldDefinition.tenant_id == event.tenant_id,
                        CRMCustomFieldDefinition.entity_kind == payload.profile_kind,
                        CRMCustomFieldDefinition.is_active.is_(True),
                        CRMCustomFieldDefinition.is_required.is_(True),
                    )
                    .limit(1)
                )
                if required_custom_field is not None:
                    raise CustomerSyncError(
                        "crm.customer.required_fields_unmapped"
                    )

                identity = await session.scalar(
                    select(ProductCustomerIdentity)
                    .where(
                        ProductCustomerIdentity.tenant_id == event.tenant_id,
                        ProductCustomerIdentity.source_product == event.source_product,
                        ProductCustomerIdentity.external_customer_id
                        == payload.external_customer_id,
                    )
                    .with_for_update()
                )
                if identity is None:
                    profile_id = uuid4()
                    session.add(
                        TenantRecord(
                            id=profile_id,
                            tenant_id=event.tenant_id,
                            organization_unit_id=organization.id,
                            record_type="crm_profile",
                        )
                    )
                    await session.flush()
                    profile = CRMProfile(
                        id=profile_id,
                        tenant_id=event.tenant_id,
                        organization_unit_id=organization.id,
                        profile_kind=payload.profile_kind,
                        display_name=payload.display_name,
                        lifecycle_stage="lead",
                    )
                    session.add(profile)
                    await session.flush()
                    identity = ProductCustomerIdentity(
                        tenant_id=event.tenant_id,
                        source_product=event.source_product,
                        external_customer_id=payload.external_customer_id,
                        profile_id=profile_id,
                    )
                    session.add(identity)
                else:
                    profile = await session.scalar(
                        select(CRMProfile)
                        .where(
                            CRMProfile.tenant_id == event.tenant_id,
                            CRMProfile.id == identity.profile_id,
                        )
                        .with_for_update()
                    )
                    if profile is None:
                        raise CustomerSyncError(
                            "crm.customer.linked_profile_unavailable"
                        )
                    if profile.archived_at is not None or profile.merged_into_profile_id is not None:
                        raise CustomerSyncError(
                            "crm.customer.linked_profile_not_writable"
                        )
                    if profile.profile_kind != payload.profile_kind:
                        raise CustomerSyncError(
                            "crm.customer.profile_kind_conflict"
                        )
                    profile.display_name = payload.display_name

                for contact in payload.contacts:
                    await self._add_contact_if_missing(
                        session,
                        tenant_id=event.tenant_id,
                        profile_id=identity.profile_id,
                        contact=contact,
                    )

                session.add(
                    AuditEvent(
                        tenant_id=event.tenant_id,
                        actor_kind="system",
                        actor_identity_id=None,
                        actor_membership_id=None,
                        action_key="integration.customer.upserted",
                        target_type="crm_profile",
                        target_key=str(identity.profile_id),
                        organization_unit_id=organization.id,
                        before_state=None,
                        after_state={
                            "source_product": event.source_product,
                            "event_id": str(event.event_id),
                            "profile_kind": payload.profile_kind,
                            "contact_count": len(payload.contacts),
                        },
                        correlation_id=event.correlation_id,
                    )
                )


    async def _process_activity(self, event: ClaimedIntegrationEvent) -> None:
        try:
            payload = CustomerActivityPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise CustomerSyncError("crm.customer.activity_invalid_payload") from exc

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
                        ProductCustomerIdentity.external_customer_id
                        == payload.external_customer_id,
                    )
                    .with_for_update()
                )
                if identity is None:
                    raise CustomerSyncError(
                        "crm.customer.activity.profile_mapping_pending",
                        retryable=True,
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
                    raise CustomerSyncError(
                        "crm.customer.activity.profile_unavailable"
                    )
                if profile.merged_into_profile_id is not None:
                    raise CustomerSyncError(
                        "crm.customer.activity.profile_merged"
                    )

                if payload.campaign_id is not None:
                    campaign = await session.scalar(
                        select(CRMMarketingCampaign).where(
                            CRMMarketingCampaign.tenant_id == event.tenant_id,
                            CRMMarketingCampaign.id == payload.campaign_id,
                            CRMMarketingCampaign.organization_unit_id == profile.organization_unit_id,
                        )
                    )
                    if campaign is None:
                        raise CustomerSyncError("crm.customer.activity.campaign_unavailable")

                activity = CRMCustomerActivity(
                    id=uuid4(),
                    tenant_id=event.tenant_id,
                    profile_id=profile.id,
                    source_product=event.source_product,
                    source_event_id=event.event_id,
                    campaign_id=payload.campaign_id,
                    activity_type=payload.activity_type,
                    channel=payload.channel,
                    source_record_id=payload.source_record_id,
                    occurred_at=event.occurred_at,
                )
                session.add(activity)
                session.add(
                    AuditEvent(
                        tenant_id=event.tenant_id,
                        actor_kind="system",
                        actor_identity_id=None,
                        actor_membership_id=None,
                        action_key="integration.customer.activity_recorded",
                        target_type="crm_customer_activity",
                        target_key=str(activity.id),
                        organization_unit_id=profile.organization_unit_id,
                        before_state=None,
                        after_state={
                            "source_product": event.source_product,
                            "source_event_id": str(event.event_id),
                            "activity_type": payload.activity_type,
                            "channel": payload.channel,
                            "campaign_id": str(payload.campaign_id) if payload.campaign_id else None,
                        },
                        correlation_id=event.correlation_id,
                    )
                )

    async def _add_contact_if_missing(
        self,
        session,
        *,
        tenant_id: UUID,
        profile_id: UUID,
        contact: CustomerContactInput,
    ) -> None:
        keyring = self._contact_keyring
        fingerprints = keyring.blind_indexes(
            tenant_id=tenant_id,
            channel=contact.channel,
            value=contact.value,
        )
        matching_fingerprint = or_(
            *[
                and_(
                    CRMContactPoint.fingerprint_key_id == key_id,
                    CRMContactPoint.match_fingerprint == fingerprint,
                )
                for key_id, fingerprint in fingerprints.items()
            ]
        )
        existing = await session.scalar(
            select(CRMContactPoint.id)
            .where(
                CRMContactPoint.tenant_id == tenant_id,
                CRMContactPoint.profile_id == profile_id,
                CRMContactPoint.channel == contact.channel,
                matching_fingerprint,
            )
            .limit(1)
        )
        if existing is not None:
            return

        encryption_key_id, encrypted_value = keyring.encrypt(
            tenant_id=tenant_id,
            profile_id=profile_id,
            channel=contact.channel,
            value=contact.value,
        )
        session.add(
            CRMContactPoint(
                id=uuid4(),
                tenant_id=tenant_id,
                profile_id=profile_id,
                channel=contact.channel,
                encrypted_value=encrypted_value,
                encryption_key_id=encryption_key_id,
                fingerprint_key_id=encryption_key_id,
                match_fingerprint=fingerprints[encryption_key_id],
                verification_status="unverified",
                is_primary=False,
            )
        )
