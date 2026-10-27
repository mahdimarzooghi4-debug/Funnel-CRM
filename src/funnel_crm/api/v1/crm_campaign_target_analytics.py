"""Portfolio view of campaign target attainment for one exact period."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
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


class PortfolioCommerceOutcome(BaseModel):
    currency: str
    campaign_count: int
    spend_amount: Decimal
    spend_observed_days: int
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    refund_event_count: int
    refunded_amount: Decimal
    net_paid_amount: Decimal
    net_paid_amount_per_paid_order: Decimal | None
    observed_paid_to_spend_multiple: Decimal | None
    observed_net_paid_to_spend_multiple: Decimal | None


class CampaignTargetPortfolioItem(BaseModel):
    campaign_id: UUID
    target_plan_id: UUID
    name: str
    organization_unit_id: UUID
    group_key: str
    commerce_access_granted: bool
    commerce_outcomes_by_currency: list[PortfolioCommerceOutcome]
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
    commerce_outcomes_by_currency: list[PortfolioCommerceOutcome]


class CampaignTargetPortfolioRead(BaseModel):
    period_start: date
    period_end: date
    organization_unit_id: UUID | None
    grouped_by: Literal["channel", "objective"]
    campaign_count: int
    campaign_list_truncated: bool
    metric_outcomes: dict[str, TargetOutcomeCounts]
    metric_variances: dict[str, CampaignTargetMetricVariance]
    commerce_outcomes_by_currency: list[PortfolioCommerceOutcome]
    commerce_basis: str
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


def _campaign_commerce_outcomes(
    measurements: list[CRMMarketingCampaignMeasurement],
    events: list[CRMProductCommerceEvent],
) -> list[PortfolioCommerceOutcome]:
    spend_by_currency: dict[str, tuple[Decimal, int]] = {}
    for row in measurements:
        if row.actual_spend_amount is None or row.actual_spend_currency is None:
            continue
        amount, days = spend_by_currency.get(row.actual_spend_currency, (Decimal("0"), 0))
        spend_by_currency[row.actual_spend_currency] = (amount + row.actual_spend_amount, days + 1)

    commerce_by_currency: dict[str, dict[str, object]] = {}
    paid_order_keys: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for event in events:
        state = commerce_by_currency.setdefault(event.currency, {
            "paid_event_count": 0,
            "paid_amount": Decimal("0"),
            "refund_event_count": 0,
            "refunded_amount": Decimal("0"),
        })
        if event.event_kind == "paid":
            state["paid_event_count"] = int(state["paid_event_count"]) + 1
            state["paid_amount"] = Decimal(state["paid_amount"]) + event.amount
            paid_order_keys[event.currency].add((event.source_product, event.order_reference))
        elif event.event_kind == "refunded":
            state["refund_event_count"] = int(state["refund_event_count"]) + 1
            state["refunded_amount"] = Decimal(state["refunded_amount"]) + event.amount

    outcomes = []
    for currency in sorted(set(spend_by_currency) | set(commerce_by_currency)):
        spend, spend_days = spend_by_currency.get(currency, (Decimal("0"), 0))
        commerce = commerce_by_currency.get(currency, {})
        paid_count = int(commerce.get("paid_event_count", 0))
        paid_amount = Decimal(commerce.get("paid_amount", Decimal("0")))
        refund_count = int(commerce.get("refund_event_count", 0))
        refunded_amount = Decimal(commerce.get("refunded_amount", Decimal("0")))
        net_paid_amount = paid_amount - refunded_amount
        paid_order_count = len(paid_order_keys.get(currency, set()))
        outcomes.append(PortfolioCommerceOutcome(
            currency=currency,
            campaign_count=1,
            spend_amount=spend,
            spend_observed_days=spend_days,
            paid_event_count=paid_count,
            paid_order_count=paid_order_count,
            paid_amount=paid_amount,
            refund_event_count=refund_count,
            refunded_amount=refunded_amount,
            net_paid_amount=net_paid_amount,
            net_paid_amount_per_paid_order=(
                (net_paid_amount / Decimal(paid_order_count)).quantize(Decimal("0.000001"))
                if paid_order_count else None
            ),
            observed_paid_to_spend_multiple=(
                (paid_amount / spend).quantize(Decimal("0.000001"))
                if paid_count and spend > 0 else None
            ),
            observed_net_paid_to_spend_multiple=(
                (net_paid_amount / spend).quantize(Decimal("0.000001"))
                if paid_count and spend > 0 else None
            ),
        ))
    return outcomes


def _aggregate_commerce_outcomes(
    outcomes: list[PortfolioCommerceOutcome],
) -> list[PortfolioCommerceOutcome]:
    totals: dict[str, dict[str, Decimal | int]] = {}
    for outcome in outcomes:
        total = totals.setdefault(outcome.currency, {
            "campaign_count": 0,
            "spend_amount": Decimal("0"),
            "spend_observed_days": 0,
            "paid_event_count": 0,
            "paid_order_count": 0,
            "paid_amount": Decimal("0"),
            "refund_event_count": 0,
            "refunded_amount": Decimal("0"),
            "net_paid_amount": Decimal("0"),
        })
        for key in total:
            total[key] = total[key] + getattr(outcome, key)

    results = []
    for currency, total in sorted(totals.items()):
        spend = Decimal(total["spend_amount"])
        paid_amount = Decimal(total["paid_amount"])
        net_paid_amount = Decimal(total["net_paid_amount"])
        paid_count = int(total["paid_event_count"])
        paid_order_count = int(total["paid_order_count"])
        results.append(PortfolioCommerceOutcome(
            currency=currency,
            campaign_count=int(total["campaign_count"]),
            spend_amount=spend,
            spend_observed_days=int(total["spend_observed_days"]),
            paid_event_count=paid_count,
            paid_order_count=paid_order_count,
            paid_amount=paid_amount,
            refund_event_count=int(total["refund_event_count"]),
            refunded_amount=Decimal(total["refunded_amount"]),
            net_paid_amount=net_paid_amount,
            net_paid_amount_per_paid_order=(
                (net_paid_amount / Decimal(paid_order_count)).quantize(Decimal("0.000001"))
                if paid_order_count else None
            ),
            observed_paid_to_spend_multiple=(
                (paid_amount / spend).quantize(Decimal("0.000001"))
                if paid_count and spend > 0 else None
            ),
            observed_net_paid_to_spend_multiple=(
                (net_paid_amount / spend).quantize(Decimal("0.000001"))
                if paid_count and spend > 0 else None
            ),
        ))
    return results


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
    commerce_permitted_scopes = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.commerce_event:view")
    )).all())
    commerce_authorized_campaigns = [
        row[1] for row in result_rows
        if row[3] in commerce_permitted_scopes
    ]
    if commerce_authorized_campaigns:
        commerce_start = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
        commerce_end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
        commerce_rows = (await context.session.scalars(
            select(CRMProductCommerceEvent).where(
                CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                CRMProductCommerceEvent.campaign_id.in_(commerce_authorized_campaigns),
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
        commerce_access_granted = campaign_id in commerce_authorized_campaigns
        campaign_measurements = measurements_by_campaign[campaign_id]
        campaign_events = commerce_by_campaign[campaign_id]
        if plan.min_net_paid_to_spend is not None and commerce_access_granted:
            net_result = evaluate_net_paid_to_spend_target(
                plan, campaign_measurements, campaign_events
            )
            if net_result is not None:
                item_metrics["period_net_paid_to_spend"] = net_result
        items.append(CampaignTargetPortfolioItem(
            campaign_id=campaign_id,
            target_plan_id=plan.id,
            name=name,
            organization_unit_id=unit_id,
            group_key=group_key,
            commerce_access_granted=commerce_access_granted,
            commerce_outcomes_by_currency=(
                _campaign_commerce_outcomes(campaign_measurements, campaign_events)
                if commerce_access_granted else []
            ),
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
            commerce_outcomes_by_currency=_aggregate_commerce_outcomes([
                outcome for item in group_items for outcome in item.commerce_outcomes_by_currency
            ]),
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
    if any(item.commerce_access_granted for item in items):
        for key in ("net_paid_amount", "net_paid_amount_per_paid_order", "period_net_paid_to_spend"):
            definition = get_metric_definition(key)
            if definition is not None:
                metric_definitions[key] = definition

    return CampaignTargetPortfolioRead(
        period_start=period_start,
        period_end=period_end,
        organization_unit_id=organization_unit_id,
        grouped_by=grouped_by,
        campaign_count=len(items),
        campaign_list_truncated=truncated,
        metric_outcomes=metric_outcomes,
        metric_variances=_metric_variances(items),
        commerce_outcomes_by_currency=_aggregate_commerce_outcomes([
            outcome for item in items for outcome in item.commerce_outcomes_by_currency
        ]),
        commerce_basis=(
            "Only campaign-linked paid and refunded events are included. Spend and commerce are kept in the same currency; "
            "portfolio multiples divide pooled full-period sums and are descriptive, not causal or accounting profit."
        ),
        metric_definitions=metric_definitions,
        period_calendar_days=(period_end - period_start).days + 1,
        coverage_basis=(
            "For each evaluated metric, observed days divided by calendar days in the plan period. "
            "Paired metrics count only days with compatible recorded inputs; missing days are not zero."
        ),
        groups=groups,
        campaigns=items,
    )
