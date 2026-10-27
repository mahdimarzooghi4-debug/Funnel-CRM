"""Portfolio view of campaign target attainment for one exact period."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_metric_catalog import MetricDefinition, get_metric_definition
from funnel_crm.api.v1.crm_campaign_targets import (
    TargetMetricEvaluation,
    evaluate_net_paid_to_spend_target,
    evaluate_plan_metrics,
)
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMProductCommerceEvent,
)
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/campaign-target-performance",
    tags=["CRM marketing analytics"],
)


class TargetOutcomeCounts(BaseModel):
    evaluated: int
    met: int
    not_met: int
    no_data: int


class CampaignTargetPortfolioItem(BaseModel):
    campaign_id: UUID
    target_plan_id: UUID
    name: str
    organization_unit_id: UUID
    group_key: str
    metrics: dict[str, TargetMetricEvaluation]


class CampaignTargetMetricVariance(BaseModel):
    targeted_campaign_count: int
    complete_campaign_count: int
    incomplete_campaign_count: int
    target_total: int
    complete_actual_total: int
    complete_campaign_target_total: int
    complete_variance: int
    incomplete_target_total: int
    partial_actual_total: int


class CampaignTargetPortfolioGroup(BaseModel):
    key: str
    campaign_count: int
    metric_outcomes: dict[str, TargetOutcomeCounts]
    metric_variances: dict[str, CampaignTargetMetricVariance]


class CampaignTargetPortfolioRead(BaseModel):
    period_start: date
    period_end: date
    organization_unit_id: UUID | None
    grouped_by: Literal["channel", "objective"]
    campaign_count: int
    campaign_list_truncated: bool
    metric_outcomes: dict[str, TargetOutcomeCounts]
    metric_variances: dict[str, CampaignTargetMetricVariance]
    metric_definitions: dict[str, MetricDefinition]
    period_calendar_days: int
    coverage_basis: str
    groups: list[CampaignTargetPortfolioGroup]
    campaigns: list[CampaignTargetPortfolioItem]


def _metric_variances(
    items: list[CampaignTargetPortfolioItem],
) -> dict[str, CampaignTargetMetricVariance]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {
        "targeted_campaign_count": 0,
        "complete_campaign_count": 0,
        "incomplete_campaign_count": 0,
        "target_total": 0,
        "complete_actual_total": 0,
        "complete_campaign_target_total": 0,
        "incomplete_target_total": 0,
        "partial_actual_total": 0,
    })
    for item in items:
        for metric_name in ("impressions", "clicks", "leads", "conversions"):
            result = item.metrics.get(metric_name)
            if result is None:
                continue
            bucket = totals[metric_name]
            target = int(result.target)
            bucket["targeted_campaign_count"] += 1
            bucket["target_total"] += target
            is_complete = result.observed_days >= result.period_days
            if not is_complete:
                bucket["incomplete_campaign_count"] += 1
                bucket["incomplete_target_total"] += target
                if result.actual is not None:
                    bucket["partial_actual_total"] += int(result.actual)
                continue
            bucket["complete_campaign_count"] += 1
            bucket["complete_actual_total"] += int(result.actual or 0)
            bucket["complete_campaign_target_total"] += target

    return {
        name: CampaignTargetMetricVariance(
            **values,
            complete_variance=(values["complete_actual_total"] - values["complete_campaign_target_total"]),
        )
        for name, values in sorted(totals.items())
    }


def _outcomes(
    items: list[CampaignTargetPortfolioItem],
) -> dict[str, TargetOutcomeCounts]:
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"evaluated": 0, "met": 0, "not_met": 0, "no_data": 0}
    )
    for item in items:
        for name, result in item.metrics.items():
            counts[name]["evaluated"] += 1
            counts[name][result.status] += 1
    return {name: TargetOutcomeCounts(**values) for name, values in sorted(counts.items())}


@router.get(
    "/portfolio",
    response_model=CampaignTargetPortfolioRead,
    operation_id="reviewCRMMarketingCampaignTargetPortfolio",
)
async def review_campaign_target_portfolio(
    period_start: date,
    period_end: date,
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    grouped_by: Literal["channel", "objective"] = Query(default="channel"),
) -> CampaignTargetPortfolioRead:
    if period_start > period_end or (period_end - period_start).days >= 366:
        raise HTTPException(status_code=422, detail="Period must be ordered and no longer than 366 days")

    permitted_scopes = crm_scope_ids(context, permission_key="crm.campaign:view")
    if organization_unit_id is not None and organization_unit_id not in permitted_scopes:
        raise HTTPException(status_code=403, detail="Campaign analytics is not authorized for this organization scope")

    statement = (
        select(
            CRMMarketingCampaignTargetPlan,
            CRMMarketingCampaign.id,
            CRMMarketingCampaign.name,
            CRMMarketingCampaign.organization_unit_id,
            CRMMarketingCampaign.channel,
            CRMMarketingCampaign.objective_key,
        )
        .join(
            CRMMarketingCampaign,
            (CRMMarketingCampaign.tenant_id == CRMMarketingCampaignTargetPlan.tenant_id)
            & (CRMMarketingCampaign.organization_unit_id == CRMMarketingCampaignTargetPlan.organization_unit_id)
            & (CRMMarketingCampaign.id == CRMMarketingCampaignTargetPlan.campaign_id),
        )
        .where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.organization_unit_id.in_(permitted_scopes),
            CRMMarketingCampaignTargetPlan.period_start == period_start,
            CRMMarketingCampaignTargetPlan.period_end == period_end,
        )
    )
    if organization_unit_id is not None:
        statement = statement.where(
            CRMMarketingCampaignTargetPlan.organization_unit_id == organization_unit_id
        )
    result_rows = (await context.session.execute(
        statement.order_by(CRMMarketingCampaign.name, CRMMarketingCampaign.id).limit(1001)
    )).all()
    truncated = len(result_rows) > 1000
    result_rows = result_rows[:1000]
    campaign_ids = [row[1] for row in result_rows]
    measurements = []
    if campaign_ids:
        measurements = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.campaign_id.in_(campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= period_start,
                CRMMarketingCampaignMeasurement.measured_on <= period_end,
            ).order_by(CRMMarketingCampaignMeasurement.measured_on)
        )).all()

    measurements_by_campaign: dict[UUID, list[CRMMarketingCampaignMeasurement]] = defaultdict(list)
    for measurement in measurements:
        measurements_by_campaign[measurement.campaign_id].append(measurement)

    commerce_by_campaign: dict[UUID, list[CRMProductCommerceEvent]] = defaultdict(list)
    net_target_campaigns = [
        row[1] for row in result_rows
        if row[0].min_net_paid_to_spend is not None
        and await has_crm_permission(
            context, permission_key="crm.commerce_event:view", organization_unit_id=row[3]
        )
    ]
    if net_target_campaigns:
        commerce_start = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
        commerce_end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
        commerce_rows = (await context.session.scalars(
            select(CRMProductCommerceEvent).where(
                CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                CRMProductCommerceEvent.campaign_id.in_(net_target_campaigns),
                CRMProductCommerceEvent.occurred_at >= commerce_start,
                CRMProductCommerceEvent.occurred_at < commerce_end,
            ).order_by(CRMProductCommerceEvent.occurred_at)
        )).all()
        for event in commerce_rows:
            commerce_by_campaign[event.campaign_id].append(event)

    items: list[CampaignTargetPortfolioItem] = []
    for plan, campaign_id, name, unit_id, channel, objective in result_rows:
        group_key = channel if grouped_by == "channel" else objective
        item_metrics = evaluate_plan_metrics(plan, measurements_by_campaign[campaign_id])
        if plan.min_net_paid_to_spend is not None and campaign_id in net_target_campaigns:
            net_result = evaluate_net_paid_to_spend_target(
                plan, measurements_by_campaign[campaign_id], commerce_by_campaign[campaign_id]
            )
            if net_result is not None:
                item_metrics["period_net_paid_to_spend"] = net_result
        items.append(CampaignTargetPortfolioItem(
            campaign_id=campaign_id,
            target_plan_id=plan.id,
            name=name,
            organization_unit_id=unit_id,
            group_key=group_key,
            metrics=item_metrics,
        ))

    grouped: dict[str, list[CampaignTargetPortfolioItem]] = defaultdict(list)
    for item in items:
        grouped[item.group_key].append(item)
    groups = [
        CampaignTargetPortfolioGroup(
            key=key,
            campaign_count=len(group_items),
            metric_outcomes=_outcomes(group_items),
            metric_variances=_metric_variances(group_items),
        )
        for key, group_items in sorted(grouped.items())
    ]

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign_target_portfolio.reviewed",
        target_type="crm_marketing_campaign_target_portfolio",
        target_key=f"{period_start.isoformat()}:{period_end.isoformat()}",
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "grouped_by": grouped_by,
            "campaign_count": len(items),
            "truncated": truncated,
        },
        correlation_id=None,
    ))
    await context.session.flush()

    metric_outcomes = _outcomes(items)
    metric_definitions = {
        key: definition
        for key in metric_outcomes
        if (definition := get_metric_definition(key)) is not None
    }

    return CampaignTargetPortfolioRead(
        period_start=period_start,
        period_end=period_end,
        organization_unit_id=organization_unit_id,
        grouped_by=grouped_by,
        campaign_count=len(items),
        campaign_list_truncated=truncated,
        metric_outcomes=metric_outcomes,
        metric_variances=_metric_variances(items),
        metric_definitions=metric_definitions,
        period_calendar_days=(period_end - period_start).days + 1,
        coverage_basis=(
            "For each evaluated metric, observed days divided by calendar days in the plan period. "
            "Paired metrics count only days with compatible recorded inputs; missing days are not zero."
        ),
        groups=groups,
        campaigns=items,
    )
