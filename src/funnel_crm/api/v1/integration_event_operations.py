"""Tenant-administered inspection and safe redrive for failed product events."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import AuditEvent, IntegrationEventInbox, Workspace
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/integrations/events", tags=["product event operations"])


class FailedProductEventRead(BaseModel):
    id: UUID
    event_id: UUID
    source_product: str
    event_type: str
    contract_name: str
    contract_version: int
    processing_status: str
    attempt_count: int
    last_error_code: str | None
    occurred_at: datetime
    received_at: datetime
    available_at: datetime


class ProductEventRetryRead(BaseModel):
    id: UUID
    processing_status: str
    attempt_count: int
    available_at: datetime


async def _require_manage(context: TenantSessionContext) -> UUID:
    tenant_id = context.access.tenant_id
    root_id = await context.session.scalar(
        select(Workspace.root_organization_id).where(Workspace.id == tenant_id)
    )
    if root_id is None or not await has_crm_permission(
        context,
        permission_key="crm.integration:manage",
        organization_unit_id=root_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Product event operations are not authorized",
        )
    return root_id


@router.get(
    "/failed",
    response_model=list[FailedProductEventRead],
    operation_id="listFailedProductEvents",
    summary="List failed product events without exposing payloads",
)
async def list_failed_product_events(
    limit: int = Query(default=50, ge=1, le=100),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[FailedProductEventRead]:
    await _require_manage(context)
    rows = (
        await context.session.scalars(
            select(IntegrationEventInbox)
            .where(
                IntegrationEventInbox.tenant_id == context.access.tenant_id,
                IntegrationEventInbox.processing_status == "failed",
            )
            .order_by(
                IntegrationEventInbox.received_at.desc(),
                IntegrationEventInbox.id,
            )
            .limit(limit)
        )
    ).all()
    return [
        FailedProductEventRead(
            id=row.id,
            event_id=row.event_id,
            source_product=row.source_product,
            event_type=row.event_type,
            contract_name=row.contract_name,
            contract_version=row.contract_version,
            processing_status=row.processing_status,
            attempt_count=row.attempt_count,
            last_error_code=row.last_error_code,
            occurred_at=row.occurred_at,
            received_at=row.received_at,
            available_at=row.available_at,
        )
        for row in rows
    ]


@router.post(
    "/{event_row_id}/retry",
    response_model=ProductEventRetryRead,
    operation_id="retryFailedProductEvent",
    summary="Requeue one failed product event for processing",
)
async def retry_failed_product_event(
    event_row_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> ProductEventRetryRead:
    root_id = await _require_manage(context)
    row = await context.session.scalar(
        select(IntegrationEventInbox)
        .where(
            IntegrationEventInbox.tenant_id == context.access.tenant_id,
            IntegrationEventInbox.id == event_row_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Product event not found")
    if row.processing_status != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only terminally failed product events can be retried",
        )

    prior_attempt_count = row.attempt_count
    prior_error_code = row.last_error_code
    row.processing_status = "received"
    row.attempt_count = 0
    row.available_at = datetime.now(timezone.utc)
    row.lease_token = None
    row.lease_until = None
    row.last_error_code = None
    row.processed_at = None
    await context.session.flush()

    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="integration.event.requeued",
            target_type="integration_event",
            target_key=str(row.id),
            organization_unit_id=root_id,
            before_state={
                "processing_status": "failed",
                "attempt_count": prior_attempt_count,
                "last_error_code": prior_error_code,
            },
            after_state={
                "processing_status": row.processing_status,
                "attempt_count": row.attempt_count,
            },
            correlation_id=row.correlation_id,
        )
    )
    await context.session.flush()
    return ProductEventRetryRead(
        id=row.id,
        processing_status=row.processing_status,
        attempt_count=row.attempt_count,
        available_at=row.available_at,
    )
