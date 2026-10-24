"""Read-only reporting for source-recorded paid orders and refunds."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMProductCommerceEvent,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/commerce-outcomes",
    tags=["CRM commerce outcomes"],
)


class CommerceOutcomeBucket(BaseModel):
    campaign_id: UUID | None
    campaign_name: str | None
    event_kind: Literal["paid", "refunded"]
    currency: str
    event_count: int
    distinct_order_count: int
    amount_total: Decimal


class CommerceOutcomeReport(BaseModel):
    organization_unit_id: UUID
    period_start: date
    period_end: date
    generated_at: datetime
    paid_event_count: int
    refund_event_count: int
    buckets: list[CommerceOutcomeBucket]


@router.get("", response_model=CommerceOutcomeReport,
            operation_id="getCRMCommerceOutcomeReport")
async def get_commerce_outcomes(
    organization_unit_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    campaign_id: UUID | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CommerceOutcomeReport:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="Period start must not be after period end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Reports are limited to 366 calendar days")
    for permission in ("crm.campaign:view", "crm.commerce_event:view"):
        if not await has_crm_permission(
            context, permission_key=permission,
            organization_unit_id=organization_unit_id,
        ):
            raise HTTPException(status_code=403, detail="Commerce outcome report is not authorized")

    start_at = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(
        period_end + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    filters = [
        CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
        CRMProductCommerceEvent.organization_unit_id == organization_unit_id,
        CRMProductCommerceEvent.occurred_at >= start_at,
        CRMProductCommerceEvent.occurred_at < end_exclusive,
    ]
    if campaign_id is not None:
        filters.append(CRMProductCommerceEvent.campaign_id == campaign_id)

    rows = (await context.session.execute(
        select(
            CRMProductCommerceEvent.campaign_id,
            CRMMarketingCampaign.name,
            CRMProductCommerceEvent.event_kind,
            CRMProductCommerceEvent.currency,
            func.count(CRMProductCommerceEvent.id).label("event_count"),
            func.count(func.distinct(CRMProductCommerceEvent.order_reference)).label("order_count"),
            func.sum(CRMProductCommerceEvent.amount).label("amount_total"),
        )
        .outerjoin(
            CRMMarketingCampaign,
            (CRMMarketingCampaign.tenant_id == CRMProductCommerceEvent.tenant_id)
            & (CRMMarketingCampaign.organization_unit_id == CRMProductCommerceEvent.organization_unit_id)
            & (CRMMarketingCampaign.id == CRMProductCommerceEvent.campaign_id),
        )
        .where(*filters)
        .group_by(
            CRMProductCommerceEvent.campaign_id,
            CRMMarketingCampaign.name,
            CRMProductCommerceEvent.event_kind,
            CRMProductCommerceEvent.currency,
        )
        .order_by(
            CRMProductCommerceEvent.campaign_id,
            CRMProductCommerceEvent.event_kind,
            CRMProductCommerceEvent.currency,
        )
    )).all()

    buckets = [
        CommerceOutcomeBucket(
            campaign_id=row.campaign_id,
            campaign_name=row.name,
            event_kind=row.event_kind,
            currency=row.currency,
            event_count=int(row.event_count),
            distinct_order_count=int(row.order_count),
            amount_total=row.amount_total or Decimal("0"),
        )
        for row in rows
    ]
    paid_event_count = sum(item.event_count for item in buckets if item.event_kind == "paid")
    refund_event_count = sum(item.event_count for item in buckets if item.event_kind == "refunded")

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_commerce_event.report_viewed",
        target_type="crm_commerce_outcome_report",
        target_key=str(campaign_id or organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "campaign_id": str(campaign_id) if campaign_id else None,
            "event_count": paid_event_count + refund_event_count,
            "bucket_count": len(buckets),
        },
        correlation_id=None,
    ))
    await context.session.flush()

    return CommerceOutcomeReport(
        organization_unit_id=organization_unit_id,
        period_start=period_start,
        period_end=period_end,
        generated_at=datetime.now(timezone.utc),
        paid_event_count=paid_event_count,
        refund_event_count=refund_event_count,
        buckets=buckets,
    )
