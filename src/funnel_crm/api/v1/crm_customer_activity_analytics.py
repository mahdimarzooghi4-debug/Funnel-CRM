"""Scoped aggregate reporting over recorded CRM customer activities."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import cast, func, select, Date as SQLDate
from sqlalchemy.ext.asyncio import AsyncSession

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import AuditEvent, CRMCustomerActivity, CRMMarketingCampaign, CRMProfile
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/customer-activities",
    tags=["CRM marketing analytics"],
)


class ActivityCategoryComparison(BaseModel):
    key: str
    current_count: int
    previous_count: int


class CustomerActivityAnalytics(BaseModel):
    window_days: int
    current_period_start: datetime
    current_period_end: datetime
    previous_period_start: datetime
    previous_period_end: datetime
    current_activity_count: int
    previous_activity_count: int
    current_profiles_with_activity: int
    previous_profiles_with_activity: int
    activity_count_change_percent: float | None
    by_channel: list[ActivityCategoryComparison]
    by_activity_type: list[ActivityCategoryComparison]


async def _period_totals(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    allowed_units: list[UUID],
    start: datetime,
    end: datetime,
    organization_unit_id: UUID | None,
) -> tuple[int, int]:
    filters = [
        CRMCustomerActivity.tenant_id == tenant_id,
        CRMCustomerActivity.occurred_at >= start,
        CRMCustomerActivity.occurred_at < end,
        CRMProfile.tenant_id == tenant_id,
        CRMProfile.organization_unit_id.in_(allowed_units),
        CRMProfile.archived_at.is_(None),
        CRMProfile.merged_into_profile_id.is_(None),
    ]
    if organization_unit_id is not None:
        filters.append(CRMProfile.organization_unit_id == organization_unit_id)
    row = (
        await session.execute(
            select(
                func.count(CRMCustomerActivity.id),
                func.count(func.distinct(CRMCustomerActivity.profile_id)),
            )
            .select_from(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _category_counts(
    session: AsyncSession,
    *,
    category_column,
    tenant_id: UUID,
    allowed_units: list[UUID],
    start: datetime,
    end: datetime,
    organization_unit_id: UUID | None,
) -> dict[str, int]:
    filters = [
        CRMCustomerActivity.tenant_id == tenant_id,
        CRMCustomerActivity.occurred_at >= start,
        CRMCustomerActivity.occurred_at < end,
        CRMProfile.tenant_id == tenant_id,
        CRMProfile.organization_unit_id.in_(allowed_units),
        CRMProfile.archived_at.is_(None),
        CRMProfile.merged_into_profile_id.is_(None),
    ]
    if organization_unit_id is not None:
        filters.append(CRMProfile.organization_unit_id == organization_unit_id)
    rows = (
        await session.execute(
            select(category_column, func.count(CRMCustomerActivity.id).label("count"))
            .select_from(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
            .group_by(category_column)
            .order_by(func.count(CRMCustomerActivity.id).desc(), category_column)
            .limit(50)
        )
    ).all()
    return {str(row[0]): int(row[1]) for row in rows}


def _comparisons(
    current: dict[str, int], previous: dict[str, int]
) -> list[ActivityCategoryComparison]:
    keys = set(current) | set(previous)
    selected = sorted(
        keys,
        key=lambda key: (-(current.get(key, 0) + previous.get(key, 0)), key),
    )[:50]
    return [
        ActivityCategoryComparison(
            key=key,
            current_count=current.get(key, 0),
            previous_count=previous.get(key, 0),
        )
        for key in selected
    ]


@router.get(
    "/summary",
    response_model=CustomerActivityAnalytics,
    operation_id="getCustomerActivityAnalytics",
    summary="Compare recorded customer activities across two periods",
)
async def get_customer_activity_analytics(
    context: TenantSessionContext = Depends(require_tenant_session),
    window_days: int = Query(default=30, ge=1, le=365),
    organization_unit_id: UUID | None = None,
) -> CustomerActivityAnalytics:
    """Return aggregate counts, never customer-level rows or inferred revenue."""
    allowed_units = crm_scope_ids(context, permission_key="crm.profile:view")
    if organization_unit_id is not None:
        if not await has_crm_permission(
            context,
            permission_key="crm.profile:view",
            organization_unit_id=organization_unit_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CRM organization scope not found",
            )
    else:
        scope_count = await context.session.scalar(
            select(func.count()).select_from(allowed_units.subquery())
        )
        if not scope_count:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CRM profile view is not authorized for this organization scope",
            )

    current_end = datetime.now(timezone.utc)
    current_start = current_end - timedelta(days=window_days)
    previous_start = current_end - timedelta(days=window_days * 2)
    tenant_id = context.access.tenant_id
    current_count, current_profiles = await _period_totals(
        context.session,
        tenant_id=tenant_id,
        allowed_units=allowed_units,
        start=current_start,
        end=current_end,
        organization_unit_id=organization_unit_id,
    )
    previous_count, previous_profiles = await _period_totals(
        context.session,
        tenant_id=tenant_id,
        allowed_units=allowed_units,
        start=previous_start,
        end=current_start,
        organization_unit_id=organization_unit_id,
    )
    current_channels = await _category_counts(
        context.session,
        category_column=CRMCustomerActivity.channel,
        tenant_id=tenant_id,
        allowed_units=allowed_units,
        start=current_start,
        end=current_end,
        organization_unit_id=organization_unit_id,
    )
    previous_channels = await _category_counts(
        context.session,
        category_column=CRMCustomerActivity.channel,
        tenant_id=tenant_id,
        allowed_units=allowed_units,
        start=previous_start,
        end=current_start,
        organization_unit_id=organization_unit_id,
    )
    current_types = await _category_counts(
        context.session,
        category_column=CRMCustomerActivity.activity_type,
        tenant_id=tenant_id,
        allowed_units=allowed_units,
        start=current_start,
        end=current_end,
        organization_unit_id=organization_unit_id,
    )
    previous_types = await _category_counts(
        context.session,
        category_column=CRMCustomerActivity.activity_type,
        tenant_id=tenant_id,
        allowed_units=allowed_units,
        start=previous_start,
        end=current_start,
        organization_unit_id=organization_unit_id,
    )
    change = (
        round((current_count - previous_count) * 100 / previous_count, 2)
        if previous_count
        else None
    )

    context.session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="crm_customer_activity.analytics_viewed",
            target_type="crm_customer_activity_analytics",
            target_key=str(organization_unit_id or "authorized-scope"),
            organization_unit_id=organization_unit_id,
            before_state=None,
            after_state={
                "window_days": window_days,
                "current_activity_count": current_count,
                "previous_activity_count": previous_count,
                "current_profiles_with_activity": current_profiles,
                "previous_profiles_with_activity": previous_profiles,
            },
            correlation_id=None,
        )
    )
    await context.session.flush()

    return CustomerActivityAnalytics(
        window_days=window_days,
        current_period_start=current_start,
        current_period_end=current_end,
        previous_period_start=previous_start,
        previous_period_end=current_start,
        current_activity_count=current_count,
        previous_activity_count=previous_count,
        current_profiles_with_activity=current_profiles,
        previous_profiles_with_activity=previous_profiles,
        activity_count_change_percent=change,
        by_channel=_comparisons(current_channels, previous_channels),
        by_activity_type=_comparisons(current_types, previous_types),
    )


class CampaignActivityDay(BaseModel):
    day: date
    activity_count: int


class CampaignActivityAnalytics(BaseModel):
    campaign_id: UUID
    period_start: date
    period_end: date
    activity_count: int
    profiles_with_activity: int
    by_channel: list[ActivityCategoryComparison]
    by_activity_type: list[ActivityCategoryComparison]
    daily_activity: list[CampaignActivityDay]


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignActivityAnalytics,
    operation_id="getCampaignActivityAttribution",
    summary="Summarize customer activity attributed to a campaign",
)
async def get_campaign_activity_attribution(
    campaign_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignActivityAnalytics:
    """Return scoped aggregate attribution counts without customer-level data."""
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Activity reports are limited to 366 calendar days")

    allowed_units = crm_scope_ids(context, permission_key="crm.campaign:view")
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
            CRMMarketingCampaign.organization_unit_id.in_(allowed_units),
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    start = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    filters = [
        CRMCustomerActivity.tenant_id == context.access.tenant_id,
        CRMCustomerActivity.campaign_id == campaign_id,
        CRMCustomerActivity.occurred_at >= start,
        CRMCustomerActivity.occurred_at < end,
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id == campaign.organization_unit_id,
        CRMProfile.archived_at.is_(None),
        CRMProfile.merged_into_profile_id.is_(None),
    ]
    activity_query = (
        select(CRMCustomerActivity)
        .join(
            CRMProfile,
            (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
            & (CRMProfile.id == CRMCustomerActivity.profile_id),
        )
        .where(*filters)
    )
    activity_count = int(
        await context.session.scalar(
            select(func.count(CRMCustomerActivity.id))
            .select_from(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
        ) or 0
    )
    profiles_with_activity = int(
        await context.session.scalar(
            select(func.count(func.distinct(CRMCustomerActivity.profile_id)))
            .select_from(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
        ) or 0
    )

    async def grouped_counts(column) -> list[ActivityCategoryComparison]:
        rows = (await context.session.execute(
            select(column, func.count(CRMCustomerActivity.id))
            .select_from(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
            .group_by(column)
            .order_by(func.count(CRMCustomerActivity.id).desc(), column)
        )).all()
        return [ActivityCategoryComparison(key=str(key), current_count=int(count), previous_count=0)
                for key, count in rows]

    daily_column = cast(func.timezone("UTC", CRMCustomerActivity.occurred_at), SQLDate)
    daily_rows = (await context.session.execute(
        select(daily_column, func.count(CRMCustomerActivity.id))
        .select_from(CRMCustomerActivity)
        .join(
            CRMProfile,
            (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
            & (CRMProfile.id == CRMCustomerActivity.profile_id),
        )
        .where(*filters)
        .group_by(daily_column)
        .order_by(daily_column)
    )).all()

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_campaign.activity_attribution_viewed",
        target_type="crm_marketing_campaign",
        target_key=str(campaign_id),
        organization_unit_id=campaign.organization_unit_id,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "activity_count": activity_count,
            "profiles_with_activity": profiles_with_activity,
        },
        correlation_id=None,
    ))
    await context.session.flush()

    return CampaignActivityAnalytics(
        campaign_id=campaign_id,
        period_start=period_start,
        period_end=period_end,
        activity_count=activity_count,
        profiles_with_activity=profiles_with_activity,
        by_channel=await grouped_counts(CRMCustomerActivity.channel),
        by_activity_type=await grouped_counts(CRMCustomerActivity.activity_type),
        daily_activity=[CampaignActivityDay(day=day, activity_count=int(count))
                        for day, count in daily_rows],
    )
