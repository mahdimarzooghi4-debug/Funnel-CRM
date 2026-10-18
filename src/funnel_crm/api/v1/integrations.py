"""Versioned contract for product-to-CRM event ingestion.

Authentication middleware must validate product credentials and place a
VerifiedProductConnection on request.state. Client-supplied headers or event
fields are never treated as proof of identity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
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

            sink = PostgresProductEventSink(session_factory)
    if sink is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Durable event ingestion is not configured",
        )
    receipt = await sink.accept(connection, event)
    return {"event_id": str(receipt.event_id), "accepted": True, "duplicate": receipt.duplicate}
