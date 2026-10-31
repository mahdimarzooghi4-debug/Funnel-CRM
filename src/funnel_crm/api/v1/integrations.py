"""Versioned contract for product-to-CRM event ingestion.

Authentication middleware must validate product credentials and place a
VerifiedProductConnection on request.state. Client-supplied headers or event
fields are never treated as proof of identity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

router = APIRouter(prefix="/integrations", tags=["product integrations"])
MAX_EVENT_BYTES = 64 * 1024


class ProductEventEnvelope(BaseModel):
    """Stable envelope shared by Funnel and customer product integrations."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(description="Producer-generated idempotency key.")
    tenant_id: UUID = Field(description="Workspace this event belongs to.")
    source_product: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    event_type: str = Field(min_length=3, max_length=120, pattern=r"^[a-z][a-z0-9_.-]*$")
    contract_name: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9._-]*$")
    contract_version: int = Field(ge=1, le=2_147_483_647)
    correlation_id: UUID = Field(description="Identifier shared across a business operation.")
    occurred_at: datetime
    payload: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def enforce_payload_limit(self) -> "ProductEventEnvelope":
        encoded = json.dumps(self.payload, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError(f"payload exceeds {MAX_EVENT_BYTES} bytes")
        return self


@dataclass(frozen=True)
class VerifiedProductConnection:
    """Identity produced only by trusted credential-validation middleware.

    A connection is bound to one Workspace and explicit event/version grants.
    """

    connection_id: UUID
    tenant_id: UUID
    source_product: str
    allowed_event_types: frozenset[str]
    supported_contract_versions: frozenset[tuple[str, int]]
    active: bool = True


@dataclass(frozen=True)
class EventReceipt:
    event_id: UUID
    duplicate: bool


class ProductEventSink(Protocol):
    """Durable idempotent inbox adapter. Implementations must commit before returning."""

    async def accept(
        self, connection: VerifiedProductConnection, event: ProductEventEnvelope
    ) -> EventReceipt: ...


def authorize_product_event(
    connection: VerifiedProductConnection, event: ProductEventEnvelope
) -> None:
    """Enforce that the verified product grant applies to exactly this Workspace."""
    if not connection.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Connection is disabled")
    if event.tenant_id != connection.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace is outside this connection")
    if event.source_product != connection.source_product:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Source product does not match this connection")
    if event.event_type not in connection.allowed_event_types:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Event type is not granted")
    if (event.contract_name, event.contract_version) not in connection.supported_contract_versions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Contract version is not granted")



class ProductConsentEligibilityCheck(BaseModel):
    """Point-in-time consent query from one connected product."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    external_customer_id: str = Field(min_length=1, max_length=200)
    purpose_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: str = Field(pattern=r"^(email|phone|postal_address|social_handle|website)$")

    @field_validator("external_customer_id")
    @classmethod
    def strip_external_customer_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("external_customer_id must not be blank")
        return value


class ProductConsentEligibilityItem(BaseModel):
    """One consent query in a bounded product batch."""

    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=100)
    external_customer_id: str = Field(min_length=1, max_length=200)
    purpose_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: str = Field(pattern=r"^(email|phone|postal_address|social_handle|website)$")

    @field_validator("reference", "external_customer_id")
    @classmethod
    def strip_required_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class ProductConsentEligibilityBatchCheck(BaseModel):
    """A bounded set of checks scoped to one workspace."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    checks: list[ProductConsentEligibilityItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_references(self) -> "ProductConsentEligibilityBatchCheck":
        references = [check.reference for check in self.checks]
        if len(set(references)) != len(references):
            raise ValueError("references must be unique")
        return self


class ProductConsentEligibilityResult(BaseModel):
    """Fail-closed result returned to the requesting product."""

    status: Literal["unknown", "granted", "withdrawn"]
    allowed: bool
    decision: Literal["granted", "withdrawn"] | None
    consent_event_id: int | None
    policy_version: str | None
    source_product: str | None
    recorded_at: datetime | None


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="ingestProductEvent",
    summary="Accept an event from a connected product",
    responses={
        401: {"description": "Missing or invalid product credential"},
        403: {"description": "Connection is inactive or outside its Workspace grant"},
        503: {"description": "Durable event inbox is not configured"},
    },
)
async def ingest_product_event(
    event: ProductEventEnvelope, request: Request
) -> dict[str, str | bool]:
    """Validate scope then hand off to a durable, idempotent inbox."""
    connection = getattr(request.state, "verified_product_connection", None)
    if not isinstance(connection, VerifiedProductConnection):
        from funnel_crm.platform.integration_auth import authenticate_product_credential

        connection = await authenticate_product_credential(
            getattr(request.app.state, "session_factory", None),
            tenant_id=event.tenant_id,
            authorization=request.headers.get("Authorization"),
        )
    if not isinstance(connection, VerifiedProductConnection):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid product credential is required",
        )
    authorize_product_event(connection, event)

    sink = getattr(request.app.state, "product_event_sink", None)
    if sink is None:
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is not None:
            from funnel_crm.platform.integration_sink import PostgresProductEventSink

            sink = PostgresProductEventSink(
                session_factory,
                keyring=getattr(request.app.state, "integration_payload_keyring", None),
            )
    if sink is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Durable event ingestion is not configured",
        )
    receipt = await sink.accept(connection, event)
    return {"event_id": str(receipt.event_id), "accepted": True, "duplicate": receipt.duplicate}



@router.post(
    "/communication-eligibility/check",
    operation_id="checkProductCommunicationEligibility",
    summary="Check live CRM consent before a product communicates",
    responses={
        401: {"description": "Missing or invalid product credential"},
        403: {"description": "Connection is inactive or lacks the read contract"},
        503: {"description": "CRM consent service is not configured"},
    },
)
async def check_product_communication_eligibility(
    payload: ProductConsentEligibilityCheck, request: Request
) -> ProductConsentEligibilityResult:
    """Read the current CRM decision using only a verified product grant."""
    connection = getattr(request.state, "verified_product_connection", None)
    if not isinstance(connection, VerifiedProductConnection):
        from funnel_crm.platform.integration_auth import authenticate_product_credential

        connection = await authenticate_product_credential(
            getattr(request.app.state, "session_factory", None),
            tenant_id=payload.tenant_id,
            authorization=request.headers.get("Authorization"),
        )
    if not isinstance(connection, VerifiedProductConnection):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid product credential is required",
        )
    if not connection.active:
        raise HTTPException(status_code=403, detail="Connection is disabled")
    if payload.tenant_id != connection.tenant_id:
        raise HTTPException(status_code=403, detail="Workspace is outside this connection")
    if ("crm.customer.communication_eligibility", 1) not in connection.supported_contract_versions:
        raise HTTPException(status_code=403, detail="Consent eligibility contract is not granted")

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CRM consent service is not configured",
        )

    from sqlalchemy import select, text

    from funnel_crm.platform.models import (
        CRMCommunicationConsentEvent,
        CRMProfile,
        ProductCustomerIdentity,
    )

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(connection.tenant_id)},
            )
            identity = await session.scalar(
                select(ProductCustomerIdentity).where(
                    ProductCustomerIdentity.tenant_id == connection.tenant_id,
                    ProductCustomerIdentity.source_product == connection.source_product,
                    ProductCustomerIdentity.external_customer_id
                    == payload.external_customer_id,
                )
            )
            if identity is None:
                return ProductConsentEligibilityResult(
                    status="unknown", allowed=False, decision=None,
                    consent_event_id=None, policy_version=None,
                    source_product=None, recorded_at=None
                )

            profile = await session.scalar(
                select(CRMProfile).where(
                    CRMProfile.tenant_id == connection.tenant_id,
                    CRMProfile.id == identity.profile_id,
                    CRMProfile.archived_at.is_(None),
                    CRMProfile.merged_into_profile_id.is_(None),
                )
            )
            if profile is None:
                return ProductConsentEligibilityResult(
                    status="unknown", allowed=False, decision=None,
                    consent_event_id=None, policy_version=None,
                    source_product=None, recorded_at=None
                )

            latest = await session.scalar(
                select(CRMCommunicationConsentEvent)
                .where(
                    CRMCommunicationConsentEvent.tenant_id == connection.tenant_id,
                    CRMCommunicationConsentEvent.profile_id == profile.id,
                    CRMCommunicationConsentEvent.purpose_key == payload.purpose_key,
                    CRMCommunicationConsentEvent.channel == payload.channel,
                )
                .order_by(
                    CRMCommunicationConsentEvent.recorded_at.desc(),
                    CRMCommunicationConsentEvent.id.desc(),
                )
                .limit(1)
            )
            if latest is None:
                return ProductConsentEligibilityResult(
                    status="unknown", allowed=False, decision=None,
                    consent_event_id=None, policy_version=None,
                    source_product=None, recorded_at=None
                )
            return ProductConsentEligibilityResult(
                status=latest.decision,
                allowed=latest.decision == "granted",
                decision=latest.decision,
                consent_event_id=latest.id,
                policy_version=latest.policy_version,
                source_product=latest.source_product,
                recorded_at=latest.recorded_at,
            )


class ProductConsentEligibilityBatchItemResult(ProductConsentEligibilityResult):
    """Eligibility result correlated to one caller-provided reference."""

    reference: str


class ProductConsentEligibilityBatchResult(BaseModel):
    """Ordered results for one bounded batch request."""

    checks: list[ProductConsentEligibilityBatchItemResult]


@router.post(
    "/communication-eligibility/check-batch",
    operation_id="checkProductCommunicationEligibilityBatch",
    summary="Check live CRM consent for a bounded batch of customers",
    responses={
        401: {"description": "Missing or invalid product credential"},
        403: {"description": "Connection is inactive or lacks the read contract"},
        503: {"description": "CRM consent service is not configured"},
    },
)
async def check_product_communication_eligibility_batch(
    payload: ProductConsentEligibilityBatchCheck, request: Request
) -> ProductConsentEligibilityBatchResult:
    """Resolve at most 100 checks with tenant-scoped set queries."""
    connection = getattr(request.state, "verified_product_connection", None)
    if not isinstance(connection, VerifiedProductConnection):
        from funnel_crm.platform.integration_auth import authenticate_product_credential

        connection = await authenticate_product_credential(
            getattr(request.app.state, "session_factory", None),
            tenant_id=payload.tenant_id,
            authorization=request.headers.get("Authorization"),
        )
    if not isinstance(connection, VerifiedProductConnection):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid product credential is required",
        )
    if not connection.active:
        raise HTTPException(status_code=403, detail="Connection is disabled")
    if payload.tenant_id != connection.tenant_id:
        raise HTTPException(status_code=403, detail="Workspace is outside this connection")
    if ("crm.customer.communication_eligibility", 1) not in connection.supported_contract_versions:
        raise HTTPException(status_code=403, detail="Consent eligibility contract is not granted")

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CRM consent service is not configured",
        )

    from sqlalchemy import func, select, text, tuple_

    from funnel_crm.platform.models import (
        CRMCommunicationConsentEvent,
        CRMProfile,
        ProductCustomerIdentity,
    )

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(connection.tenant_id)},
            )
            external_ids = list(dict.fromkeys(
                check.external_customer_id for check in payload.checks
            ))
            identity_rows = (
                await session.scalars(
                    select(ProductCustomerIdentity).where(
                        ProductCustomerIdentity.tenant_id == connection.tenant_id,
                        ProductCustomerIdentity.source_product == connection.source_product,
                        ProductCustomerIdentity.external_customer_id.in_(external_ids),
                    )
                )
            ).all()
            identity_by_external_id = {
                identity.external_customer_id: identity for identity in identity_rows
            }

            profile_ids = list(dict.fromkeys(
                identity.profile_id for identity in identity_rows
            ))
            profiles = (
                await session.scalars(
                    select(CRMProfile).where(
                        CRMProfile.tenant_id == connection.tenant_id,
                        CRMProfile.id.in_(profile_ids),
                        CRMProfile.archived_at.is_(None),
                        CRMProfile.merged_into_profile_id.is_(None),
                    )
                )
            ).all() if profile_ids else []
            valid_profile_ids = {profile.id for profile in profiles}

            check_keys = {
                (
                    identity_by_external_id[check.external_customer_id].profile_id,
                    check.purpose_key,
                    check.channel,
                )
                for check in payload.checks
                if check.external_customer_id in identity_by_external_id
                and identity_by_external_id[check.external_customer_id].profile_id
                in valid_profile_ids
            }
            latest_by_key = {}
            if check_keys:
                ranked_events = (
                    select(
                        CRMCommunicationConsentEvent.id.label("event_id"),
                        func.row_number()
                        .over(
                            partition_by=(
                                CRMCommunicationConsentEvent.profile_id,
                                CRMCommunicationConsentEvent.purpose_key,
                                CRMCommunicationConsentEvent.channel,
                            ),
                            order_by=(
                                CRMCommunicationConsentEvent.recorded_at.desc(),
                                CRMCommunicationConsentEvent.id.desc(),
                            ),
                        )
                        .label("event_rank"),
                    )
                    .where(
                        CRMCommunicationConsentEvent.tenant_id == connection.tenant_id,
                        tuple_(
                            CRMCommunicationConsentEvent.profile_id,
                            CRMCommunicationConsentEvent.purpose_key,
                            CRMCommunicationConsentEvent.channel,
                        ).in_(list(check_keys)),
                    )
                    .subquery()
                )
                latest_rows = (
                    await session.scalars(
                        select(CRMCommunicationConsentEvent)
                        .join(
                            ranked_events,
                            ranked_events.c.event_id == CRMCommunicationConsentEvent.id,
                        )
                        .where(ranked_events.c.event_rank == 1)
                    )
                ).all()
                latest_by_key = {
                    (row.profile_id, row.purpose_key, row.channel): row
                    for row in latest_rows
                }

            results = []
            for check in payload.checks:
                identity = identity_by_external_id.get(check.external_customer_id)
                profile_id = identity.profile_id if identity is not None else None
                if profile_id not in valid_profile_ids:
                    latest = None
                else:
                    latest = latest_by_key.get(
                        (profile_id, check.purpose_key, check.channel)
                    )
                if latest is None:
                    result = ProductConsentEligibilityResult(
                        status="unknown",
                        allowed=False,
                        decision=None,
                        consent_event_id=None,
                        policy_version=None,
                        source_product=None,
                        recorded_at=None,
                    )
                else:
                    result = ProductConsentEligibilityResult(
                        status=latest.decision,
                        allowed=latest.decision == "granted",
                        decision=latest.decision,
                        consent_event_id=latest.id,
                        policy_version=latest.policy_version,
                        source_product=latest.source_product,
                        recorded_at=latest.recorded_at,
                    )
                results.append(
                    ProductConsentEligibilityBatchItemResult(
                        reference=check.reference,
                        **result.model_dump(),
                    )
                )
            return ProductConsentEligibilityBatchResult(checks=results)
