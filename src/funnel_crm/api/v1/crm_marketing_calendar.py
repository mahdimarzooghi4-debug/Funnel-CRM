"""Timeline view of planned campaigns and CRM work items for marketing teams."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import CRMMarketingCampaign, CRMWorkItem
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/marketing-calendar",
    tags=["CRM marketing calendar"],
)


class MarketingCalendarEvent(BaseModel):
    id: UUID
    kind: Literal["campaign", "work_item"]
    title: str
    organization_unit_id: UUID
    start_date: date
    end_date: date
    status: str
    campaign_id: UUID | None
    channel: str | None
    objective_key: str | None
    priority: str | None
    assigned_membership_id: UUID | None


class MarketingCalendarResponse(BaseModel):
    period_start: date
    period_end: date
    organization_unit_id: UUID | None
    visible_sources: list[Literal["campaigns", "work_items"]]
    events: list[MarketingCalendarEvent]
    has_more: bool
    basis: str


@router.get(
    "/events",
    response_model=MarketingCalendarResponse,
    operation_id="getCRMMarketingCalendarEvents",
)
async def get_marketing_calendar_events(
    period_start: date = Query(...),
    period_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> MarketingCalendarResponse:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 92:
        raise HTTPException(status_code=422, detail="Marketing calendar range is limited to 93 days")

    campaign_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.campaign:view")
    )).all())
    work_item_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.work_item:view")
    )).all())
    visible_units = campaign_units | work_item_units
    if organization_unit_id is not None:
        if organization_unit_id not in visible_units:
            raise HTTPException(status_code=403, detail="Marketing calendar is not authorized for this organization scope")
        campaign_units.intersection_update({organization_unit_id})
        work_item_units.intersection_update({organization_unit_id})

    tenant_id = context.access.tenant_id
    start_at = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    events: list[MarketingCalendarEvent] = []
    has_more = False
    query_limit = limit + 1

    if campaign_units:
        campaigns = (await context.session.scalars(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.organization_unit_id.in_(campaign_units),
                CRMMarketingCampaign.starts_at.is_not(None),
                CRMMarketingCampaign.starts_at < end_at,
                or_(CRMMarketingCampaign.ends_at.is_(None), CRMMarketingCampaign.ends_at >= start_at),
            ).order_by(CRMMarketingCampaign.starts_at, CRMMarketingCampaign.id)
            .limit(query_limit)
        )).all()
        has_more = has_more or len(campaigns) > limit
        for campaign in campaigns[:limit]:
            events.append(MarketingCalendarEvent(
                id=campaign.id,
                kind="campaign",
                title=campaign.name,
                organization_unit_id=campaign.organization_unit_id,
                start_date=campaign.starts_at.date(),
                end_date=(campaign.ends_at or campaign.starts_at).date(),
                status=campaign.status,
                campaign_id=campaign.id,
                channel=campaign.channel,
                objective_key=campaign.objective_key,
                priority=None,
                assigned_membership_id=None,
            ))

    if work_item_units:
        work_items = (await context.session.scalars(
            select(CRMWorkItem).where(
                CRMWorkItem.tenant_id == tenant_id,
                CRMWorkItem.organization_unit_id.in_(work_item_units),
                CRMWorkItem.due_at >= start_at,
                CRMWorkItem.due_at < end_at,
            ).order_by(CRMWorkItem.due_at, CRMWorkItem.id)
            .limit(query_limit)
        )).all()
        has_more = has_more or len(work_items) > limit
        for item in work_items[:limit]:
            assert item.due_at is not None
            events.append(MarketingCalendarEvent(
                id=item.id,
                kind="work_item",
                title=item.title,
                organization_unit_id=item.organization_unit_id,
                start_date=item.due_at.date(),
                end_date=item.due_at.date(),
                status=item.status,
                campaign_id=item.campaign_id,
                channel=None,
                objective_key=None,
                priority=item.priority,
                assigned_membership_id=item.assigned_membership_id,
            ))

    events.sort(key=lambda event: (event.start_date, event.kind, event.title.casefold(), str(event.id)))
    if len(events) > limit:
        has_more = True
        events = events[:limit]
    visible_sources: list[Literal["campaigns", "work_items"]] = []
    if campaign_units:
        visible_sources.append("campaigns")
    if work_item_units:
        visible_sources.append("work_items")
    return MarketingCalendarResponse(
        period_start=period_start,
        period_end=period_end,
        organization_unit_id=organization_unit_id,
        visible_sources=visible_sources,
        events=events,
        has_more=has_more,
        basis="Campaign dates show their planned schedule; work items appear on due dates. Visibility follows campaign and work-item permissions independently.",
    )
