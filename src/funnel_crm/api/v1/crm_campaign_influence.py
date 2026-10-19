"""Transparent campaign touch to sales opportunity influence reporting.

This report shows recorded campaign activity that predates opportunities for the
same customer profile. It does not claim that a campaign caused or earned revenue.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMMarketingCampaign,
    CRMOpportunity,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/campaign-influence",
    tags=["CRM campaign influence"],
)


class CampaignInfluenceStageAmount(BaseModel):
    stage_key: str
    currency: str | None
    opportunity_count: int
    unpriced_opportunity_count: int
    opportunity_amount: Decimal | None


class CampaignInfluenceItem(BaseModel):
    campaign_id: UUID
    campaign_name: str
    channel: str
    associated_opportunity_count: int
    associated_profile_count: int
    prior_campaign_activity_count: int
    opportunities_by_stage_currency: list[CampaignInfluenceStageAmount]


class CampaignInfluenceReport(BaseModel):
    organization_unit_id: UUID
    period_start: date
    period_end: date
    generated_at: datetime
    association_rule: str
    revenue_attribution_applied: bool
    total_campaign_count: int
    has_more_campaigns: bool
    campaigns: list[CampaignInfluenceItem]


ASSOCIATION_RULE = (
    "An opportunity is associated with a campaign when its customer profile has "
    "one or more campaign-tagged CRM activities in the same tenant and organization "
    "unit at or before the opportunity creation time. An opportunity may be associated "
    "with more than one campaign. This is observed association, not causal or revenue attribution."
)


@router.get("", response_model=CampaignInfluenceReport,
            operation_id="getCRMCampaignInfluence")
async def get_campaign_influence(
    organization_unit_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    campaign_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignInfluenceReport:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="Period start must not be after period end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Reports are limited to 366 calendar days")

    for permission in ("crm.campaign:view", "crm.opportunity:view"):
        if not await has_crm_permission(
            context,
            permission_key=permission,
            organization_unit_id=organization_unit_id,
        ):
            raise HTTPException(status_code=403, detail="Campaign influence report is not authorized")

    tenant_id = context.access.tenant_id
    campaign_filters = [
        CRMMarketingCampaign.tenant_id == tenant_id,
        CRMMarketingCampaign.organization_unit_id == organization_unit_id,
    ]
    if campaign_id is not None:
        campaign_filters.append(CRMMarketingCampaign.id == campaign_id)

    total_campaign_count = int(await context.session.scalar(
        select(func.count(CRMMarketingCampaign.id)).where(*campaign_filters)
    ) or 0)
    campaigns = (await context.session.scalars(
        select(CRMMarketingCampaign)
        .where(*campaign_filters)
        .order_by(CRMMarketingCampaign.name, CRMMarketingCampaign.id)
        .limit(limit)
        .offset(offset)
    )).all()
    if campaign_id is not None and total_campaign_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found in authorized organization scope")

    period_start_at = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    period_end_exclusive = datetime.combine(
        period_end + timedelta(days=1), time.min, tzinfo=timezone.utc
    )

    matched_opportunities = (
        select(
            CRMMarketingCampaign.id.label("campaign_id"),
            CRMOpportunity.id.label("opportunity_id"),
            CRMOpportunity.profile_id.label("profile_id"),
            CRMOpportunity.stage_key.label("stage_key"),
            CRMOpportunity.currency.label("currency"),
            CRMOpportunity.amount.label("amount"),
            func.count(CRMCustomerActivity.id).label("prior_activity_count"),
        )
        .join(
            CRMCustomerActivity,
            (CRMCustomerActivity.tenant_id == CRMMarketingCampaign.tenant_id)
            & (CRMCustomerActivity.campaign_id == CRMMarketingCampaign.id),
        )
        .join(
            CRMOpportunity,
            (CRMOpportunity.tenant_id == CRMCustomerActivity.tenant_id)
            & (CRMOpportunity.profile_id == CRMCustomerActivity.profile_id)
            & (CRMOpportunity.organization_unit_id == CRMMarketingCampaign.organization_unit_id),
        )
        .where(
            CRMMarketingCampaign.tenant_id == tenant_id,
            CRMMarketingCampaign.organization_unit_id == organization_unit_id,
            CRMMarketingCampaign.id.in_([campaign.id for campaign in campaigns]),
            CRMOpportunity.tenant_id == tenant_id,
            CRMOpportunity.organization_unit_id == organization_unit_id,
            CRMOpportunity.created_at >= period_start_at,
            CRMOpportunity.created_at < period_end_exclusive,
            CRMOpportunity.profile_id.is_not(None),
            CRMCustomerActivity.occurred_at <= CRMOpportunity.created_at,
        )
        .group_by(
            CRMMarketingCampaign.id,
            CRMOpportunity.id,
            CRMOpportunity.profile_id,
            CRMOpportunity.stage_key,
            CRMOpportunity.currency,
            CRMOpportunity.amount,
        )
        .subquery()
    )

    stage_rows = (await context.session.execute(
        select(
            matched_opportunities.c.campaign_id,
            matched_opportunities.c.stage_key,
            matched_opportunities.c.currency,
            func.count(matched_opportunities.c.opportunity_id).label("opportunity_count"),
            func.sum(matched_opportunities.c.amount).label("opportunity_amount"),
            func.sum(matched_opportunities.c.prior_activity_count).label("activity_count"),
        )
        .group_by(
            matched_opportunities.c.campaign_id,
            matched_opportunities.c.stage_key,
            matched_opportunities.c.currency,
        )
    )).all()
    profile_rows = (await context.session.execute(
        select(
            matched_opportunities.c.campaign_id,
            func.count(func.distinct(matched_opportunities.c.profile_id)),
        ).group_by(matched_opportunities.c.campaign_id)
    )).all()

    stages_by_campaign: dict[UUID, list[CampaignInfluenceStageAmount]] = {}
    opportunity_counts: dict[UUID, int] = {}
    activity_counts: dict[UUID, int] = {}
    for row in stage_rows:
        stages_by_campaign.setdefault(row.campaign_id, []).append(
            CampaignInfluenceStageAmount(
                stage_key=row.stage_key,
                currency=row.currency,
                opportunity_count=int(row.opportunity_count),
                unpriced_opportunity_count=(
                    int(row.opportunity_count) if row.currency is None else 0
                ),
                opportunity_amount=row.opportunity_amount,
            )
        )
        opportunity_counts[row.campaign_id] = (
            opportunity_counts.get(row.campaign_id, 0) + int(row.opportunity_count)
        )
        activity_counts[row.campaign_id] = (
            activity_counts.get(row.campaign_id, 0) + int(row.activity_count or 0)
        )
    profiles_by_campaign = {campaign: int(count) for campaign, count in profile_rows}

    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_campaign.influence_report_viewed",
        target_type="crm_campaign_influence_report",
        target_key=str(campaign_id or organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "campaign_id": str(campaign_id) if campaign_id else None,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_campaign_count": total_campaign_count,
            "returned_campaign_count": len(campaigns),
            "limit": limit,
            "offset": offset,
        },
        correlation_id=None,
    ))
    await context.session.flush()

    return CampaignInfluenceReport(
        organization_unit_id=organization_unit_id,
        period_start=period_start,
        period_end=period_end,
        generated_at=datetime.now(timezone.utc),
        association_rule=ASSOCIATION_RULE,
        revenue_attribution_applied=False,
        total_campaign_count=total_campaign_count,
        has_more_campaigns=offset + len(campaigns) < total_campaign_count,
        campaigns=[
            CampaignInfluenceItem(
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                channel=campaign.channel,
                associated_opportunity_count=opportunity_counts.get(campaign.id, 0),
                associated_profile_count=profiles_by_campaign.get(campaign.id, 0),
                prior_campaign_activity_count=activity_counts.get(campaign.id, 0),
                opportunities_by_stage_currency=sorted(
                    stages_by_campaign.get(campaign.id, []),
                    key=lambda item: (item.stage_key, item.currency or ""),
                ),
            )
            for campaign in campaigns
        ],
    )
