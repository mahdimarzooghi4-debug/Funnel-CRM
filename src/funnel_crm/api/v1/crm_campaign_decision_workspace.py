"""Evidence-backed decision workspace for one campaign target plan."""

import csv
import io
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, tuple_

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_metric_catalog import MetricDefinition, get_metric_definition
from funnel_crm.api.v1.crm_campaign_targets import (
    CampaignTargetRead,
    evaluate_net_paid_to_spend_target,
    evaluate_plan_metrics,
)
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMMarketingLearningReview,
    CRMProductCommerceEvent,
    CRMWorkItem,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/campaigns",
    tags=["CRM campaign decision workspace"],
)

WORKSPACE_BASIS = (
    "Target metrics use CRM campaign measurements. Paid and refund outcomes use "
    "only commerce events explicitly linked to this exact campaign. Recorded-day "
    "coverage is descriptive and does not imply that unreported days had zero activity."
)
ROAS_BASIS = (
    "Observed paid amount from explicitly linked commerce events divided by "
    "recorded campaign spend in the same currency. Refunds remain separate; "
    "this is not causal or accounting revenue attribution."
)
NET_COMMERCE_BASIS = (
    "Net recorded paid amount is paid events minus refunded events in the selected "
    "currency and target period. Net amount per paid order divides by unique paid "
    "orders; the net-to-spend multiple divides by recorded spend in that currency. "
    "These measures are descriptive, not accounting profit or causal attribution."
)


class DecisionMetric(BaseModel):
    target: int | Decimal
    actual: int | Decimal | None
    status: Literal["met", "not_met", "no_data"]
    currency: str | None
    observed_days: int
    paired_days: int
    period_days: int
    recorded_day_coverage_percent: Decimal
    basis: str
    explanation: str


class DecisionCommerceCurrency(BaseModel):
    currency: str
    spend_amount: Decimal | None
    spend_observed_days: int
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    net_paid_amount: Decimal
    net_paid_amount_per_paid_order: Decimal | None
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    observed_paid_to_spend_multiple: Decimal | None
    observed_net_paid_to_spend_multiple: Decimal | None


class DecisionCommerceSourceOutcome(BaseModel):
    source_product: str
    currency: str
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    net_paid_amount: Decimal
    net_paid_amount_per_paid_order: Decimal | None


class CampaignDecisionWorkspace(BaseModel):
    campaign_id: UUID
    campaign_name: str
    organization_unit_id: UUID
    period_start: date
    period_end: date
    generated_at: datetime
    target_plan: CampaignTargetRead
    period_calendar_days: int
    coverage_basis: str
    commerce_basis: str
    metrics: dict[str, DecisionMetric]
    metric_definitions: dict[str, MetricDefinition]
    coverage_definition: MetricDefinition
    commerce_outcomes_by_currency: list[DecisionCommerceCurrency]
    commerce_outcomes_by_source_product: list[DecisionCommerceSourceOutcome]
    interpretation: str
    causal_attribution_applied: bool
    automatic_recommendation_issued: bool


class DecisionQueueCommerceCurrency(BaseModel):
    currency: str
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    net_paid_amount: Decimal
    net_paid_amount_per_paid_order: Decimal | None


class CampaignPortfolioDecisionMetric(BaseModel):
    target: int | Decimal
    actual: int | Decimal | None
    status: Literal["met", "not_met", "no_data"]
    currency: str | None
    observed_days: int
    paired_days: int
    period_days: int
    recorded_day_coverage_percent: Decimal


class CampaignPortfolioDecisionItem(BaseModel):
    campaign_id: UUID
    campaign_name: str
    organization_unit_id: UUID
    target_plan_id: UUID
    period_start: date
    period_end: date
    status: str
    attention_reasons: list[str]
    missed_metric_count: int
    no_data_metric_count: int
    recorded_day_coverage_percent: Decimal
    measurement_record_count: int
    latest_measurement_date: date | None
    metrics: dict[str, CampaignPortfolioDecisionMetric]
    commerce_outcomes_by_currency: list[DecisionQueueCommerceCurrency]
    commerce_data_status: Literal["observed", "no_linked_events", "not_authorized"]
    planned_learning_review_count: int
    evaluated_learning_review_count: int
    open_learning_action_count: int | None
    overdue_learning_action_count: int | None
    unassigned_learning_action_count: int | None
    completed_learning_action_count: int | None
    tracked_learning_action_count: int | None
    learning_action_completion_rate_percent: Decimal | None


class PeriodMetricComparison(BaseModel):
    baseline_value: int | Decimal | None
    comparison_value: int | Decimal | None
    change: int | Decimal | None
    change_percent: Decimal | None
    value_unit: Literal["count", "percent"]
    change_unit: Literal["count", "percentage_points"]
    baseline_observed_days: int
    comparison_observed_days: int


class PeriodCurrencyComparison(BaseModel):
    currency: str
    baseline_spend_amount: Decimal
    comparison_spend_amount: Decimal
    baseline_paid_amount: Decimal
    comparison_paid_amount: Decimal
    baseline_refunded_amount: Decimal
    comparison_refunded_amount: Decimal
    baseline_net_paid_amount: Decimal
    comparison_net_paid_amount: Decimal


class CampaignPortfolioPeriodComparison(BaseModel):
    generated_at: datetime
    baseline_start: date
    baseline_end: date
    comparison_start: date
    comparison_end: date
    baseline_calendar_days: int
    comparison_calendar_days: int
    baseline_campaign_count: int
    comparison_campaign_count: int
    baseline_measurement_record_count: int
    comparison_measurement_record_count: int
    baseline_recorded_days: int
    comparison_recorded_days: int
    metrics: dict[str, PeriodMetricComparison]
    financial_outcomes_by_currency: list[PeriodCurrencyComparison]
    commerce_scope_status: Literal["complete", "partial", "not_authorized"]
    interpretation: str


class CampaignPortfolioCurrencyOutcome(BaseModel):
    currency: str
    spend_measurement_count: int
    recorded_spend_amount: Decimal
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    net_paid_amount: Decimal


class CampaignPortfolioSourceProductOutcome(BaseModel):
    source_product: str
    currency: str
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    paid_amount_share_percent: Decimal | None
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    refunded_amount_share_percent: Decimal | None
    net_paid_amount: Decimal


class CampaignDecisionQueueSummary(BaseModel):
    total_count: int
    campaign_count: int
    status_counts: dict[str, int]
    attention_reason_counts: dict[str, int]
    metric_status_counts: dict[str, dict[str, int]]
    financial_period_basis: str
    commerce_scope_status: Literal["complete", "partial", "not_authorized"]
    financial_outcomes_by_currency: list[CampaignPortfolioCurrencyOutcome]
    source_product_outcomes: list[CampaignPortfolioSourceProductOutcome]


class CampaignPortfolioDecisionQueue(BaseModel):
    summary: CampaignDecisionQueueSummary
    generated_at: datetime
    period_start: date
    period_end: date
    items: list[CampaignPortfolioDecisionItem]
    total_count: int
    has_more: bool
    basis: str
    automatic_recommendation_issued: bool


def _coverage_percent(observed_days: int, period_days: int) -> Decimal:
    return (
        (Decimal(observed_days) * Decimal("100") / Decimal(period_days)).quantize(
            Decimal("0.01")
        )
        if period_days > 0
        else Decimal("0")
    )


def _status(target: Decimal, actual: Decimal | None, *, at_least: bool) -> Literal["met", "not_met", "no_data"]:
    if actual is None:
        return "no_data"
    return "met" if (actual >= target if at_least else actual <= target) else "not_met"


@router.get(
    "/decision-queue",
    response_model=CampaignPortfolioDecisionQueue,
    operation_id="getCRMCampaignPortfolioDecisionQueue",
)
async def get_campaign_portfolio_decision_queue(
    period_start: date = Query(...),
    period_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    status: Literal["review_required", "on_track_or_insufficient_signal"] | None = Query(default=None),
    attention_reason: Literal[
        "target_missed",
        "net_commerce_target_missed",
        "target_metrics_without_data",
        "net_commerce_target_without_data",
        "low_recorded_day_coverage",
    ] | None = Query(default=None),
    metric_key: Literal[
        "impressions", "clicks", "leads", "conversions", "spend",
        "cost_per_lead", "cost_per_conversion", "period_net_paid_to_spend",
    ] | None = Query(default=None),
    metric_status: Literal["met", "not_met", "no_data"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignPortfolioDecisionQueue:
    """Rank target plans that need a marketing manager's review."""
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Reports are limited to 366 calendar days")
    allowed_units = sorted(set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.campaign:view")
    )).all()), key=str)
    commerce_allowed_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.commerce_event:view")
    )).all())
    work_item_allowed_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.work_item:view")
    )).all())
    if organization_unit_id is not None:
        if organization_unit_id not in allowed_units:
            raise HTTPException(status_code=403, detail="Campaign decision queue is not authorized")
        allowed_units = [organization_unit_id]

    filters = [
        CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
        CRMMarketingCampaignTargetPlan.organization_unit_id.in_(allowed_units),
        CRMMarketingCampaignTargetPlan.period_start <= period_end,
        CRMMarketingCampaignTargetPlan.period_end >= period_start,
    ]
    total = int(await context.session.scalar(
        select(func.count(CRMMarketingCampaignTargetPlan.id)).where(*filters)
    ) or 0)
    rows = (await context.session.execute(
        select(CRMMarketingCampaignTargetPlan, CRMMarketingCampaign.name)
        .join(CRMMarketingCampaign,
              (CRMMarketingCampaign.tenant_id == CRMMarketingCampaignTargetPlan.tenant_id)
              & (CRMMarketingCampaign.id == CRMMarketingCampaignTargetPlan.campaign_id)
              & (CRMMarketingCampaign.organization_unit_id == CRMMarketingCampaignTargetPlan.organization_unit_id))
        .where(*filters)
        .order_by(CRMMarketingCampaignTargetPlan.period_end, CRMMarketingCampaign.name,
                  CRMMarketingCampaignTargetPlan.id)
    )).all()
    items = []
    for plan, campaign_name in rows:
        measurements = list((await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id == plan.organization_unit_id,
                CRMMarketingCampaignMeasurement.campaign_id == plan.campaign_id,
                CRMMarketingCampaignMeasurement.measured_on >= plan.period_start,
                CRMMarketingCampaignMeasurement.measured_on <= plan.period_end,
            )
        )).all())
        evaluated = evaluate_plan_metrics(plan, measurements)
        metric_results_by_key = {
            key: value for key, value in evaluated.items() if key != "roas"
        }
        metric_results = list(metric_results_by_key.values())
        net_result = None
        if plan.min_net_paid_to_spend is not None and plan.organization_unit_id in commerce_allowed_units:
            event_start = datetime.combine(plan.period_start, time.min, tzinfo=timezone.utc)
            event_end = datetime.combine(plan.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
            commerce_events = (await context.session.scalars(
                select(CRMProductCommerceEvent).where(
                    CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                    CRMProductCommerceEvent.organization_unit_id == plan.organization_unit_id,
                    CRMProductCommerceEvent.campaign_id == plan.campaign_id,
                    CRMProductCommerceEvent.occurred_at >= event_start,
                    CRMProductCommerceEvent.occurred_at < event_end,
                )
            )).all()
            net_result = evaluate_net_paid_to_spend_target(
                plan, measurements, list(commerce_events)
            )
            if net_result is not None:
                metric_results_by_key["period_net_paid_to_spend"] = net_result
                metric_results.append(net_result)
        queue_commerce: dict[str, dict[str, object]] = {}
        if plan.organization_unit_id in commerce_allowed_units:
            event_start = datetime.combine(plan.period_start, time.min, tzinfo=timezone.utc)
            event_end = datetime.combine(plan.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
            commerce_rows = (await context.session.execute(
                select(
                    CRMProductCommerceEvent.currency,
                    CRMProductCommerceEvent.event_kind,
                    func.count(CRMProductCommerceEvent.id).label("event_count"),
                    func.count(func.distinct(CRMProductCommerceEvent.order_reference)).label("order_count"),
                    func.sum(CRMProductCommerceEvent.amount).label("amount_total"),
                )
                .where(
                    CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                    CRMProductCommerceEvent.organization_unit_id == plan.organization_unit_id,
                    CRMProductCommerceEvent.campaign_id == plan.campaign_id,
                    CRMProductCommerceEvent.occurred_at >= event_start,
                    CRMProductCommerceEvent.occurred_at < event_end,
                )
                .group_by(
                    CRMProductCommerceEvent.currency,
                    CRMProductCommerceEvent.event_kind,
                )
            )).all()
            for commerce_row in commerce_rows:
                state = queue_commerce.setdefault(
                    commerce_row.currency,
                    {
                        "paid_event_count": 0, "paid_order_count": 0,
                        "paid_amount": Decimal("0"), "refund_event_count": 0,
                        "refunded_order_count": 0, "refunded_amount": Decimal("0"),
                    },
                )
                if commerce_row.event_kind == "paid":
                    state["paid_event_count"] = int(commerce_row.event_count)
                    state["paid_order_count"] = int(commerce_row.order_count)
                    state["paid_amount"] = commerce_row.amount_total or Decimal("0")
                else:
                    state["refund_event_count"] = int(commerce_row.event_count)
                    state["refunded_order_count"] = int(commerce_row.order_count)
                    state["refunded_amount"] = commerce_row.amount_total or Decimal("0")
        queue_commerce_metrics = [
            DecisionQueueCommerceCurrency(
                currency=currency,
                paid_event_count=int(state["paid_event_count"]),
                paid_order_count=int(state["paid_order_count"]),
                paid_amount=state["paid_amount"],
                refund_event_count=int(state["refund_event_count"]),
                refunded_order_count=int(state["refunded_order_count"]),
                refunded_amount=state["refunded_amount"],
                net_paid_amount=state["paid_amount"] - state["refunded_amount"],
                net_paid_amount_per_paid_order=(
                    ((state["paid_amount"] - state["refunded_amount"])
                     / Decimal(int(state["paid_order_count"]))).quantize(Decimal("0.000001"))
                    if state["paid_order_count"] else None
                ),
            )
            for currency, state in sorted(queue_commerce.items())
        ]
        missed = sum(1 for metric in metric_results if metric.status == "not_met")
        no_data = sum(1 for metric in metric_results if metric.status == "no_data")
        period_days = (plan.period_end - plan.period_start).days + 1
        observed_days = len({row.measured_on for row in measurements})
        coverage = _coverage_percent(observed_days, period_days)
        reasons = []
        if missed:
            reasons.append("target_missed")
        if net_result is not None and net_result.status == "not_met":
            reasons.append("net_commerce_target_missed")
        if no_data:
            reasons.append("target_metrics_without_data")
        if net_result is not None and net_result.status == "no_data":
            reasons.append("net_commerce_target_without_data")
        if coverage < Decimal("80"):
            reasons.append("low_recorded_day_coverage")
        queue_target_metrics = {
            key: CampaignPortfolioDecisionMetric(
                target=result.target,
                actual=result.actual,
                status=result.status,
                currency=result.currency,
                observed_days=result.observed_days,
                paired_days=result.paired_days,
                period_days=period_days,
                recorded_day_coverage_percent=_coverage_percent(
                    result.observed_days, period_days
                ),
            )
            for key, result in sorted(metric_results_by_key.items())
        }
        review_status_rows = (await context.session.execute(
            select(
                CRMMarketingLearningReview.status,
                func.count(CRMMarketingLearningReview.id).label("review_count"),
            )
            .where(
                CRMMarketingLearningReview.tenant_id == context.access.tenant_id,
                CRMMarketingLearningReview.organization_unit_id == plan.organization_unit_id,
                CRMMarketingLearningReview.campaign_id == plan.campaign_id,
                CRMMarketingLearningReview.target_plan_id == plan.id,
            )
            .group_by(CRMMarketingLearningReview.status)
        )).all()
        review_counts = {row.status: int(row.review_count) for row in review_status_rows}
        open_learning_action_count = None
        overdue_learning_action_count = None
        unassigned_learning_action_count = None
        completed_learning_action_count = None
        tracked_learning_action_count = None
        learning_action_completion_rate_percent = None
        if plan.organization_unit_id in work_item_allowed_units:
            open_action_status = CRMWorkItem.status.in_(("open", "in_progress"))
            action_counts = (await context.session.execute(
                select(
                    func.count(CRMWorkItem.id).filter(open_action_status).label("open_count"),
                    func.count(CRMWorkItem.id).filter(
                        open_action_status
                        & CRMWorkItem.due_at.is_not(None)
                        & (CRMWorkItem.due_at < datetime.now(timezone.utc))
                    ).label("overdue_count"),
                    func.count(CRMWorkItem.id).filter(
                        open_action_status & CRMWorkItem.assigned_membership_id.is_(None)
                    ).label("unassigned_count"),
                    func.count(CRMWorkItem.id).filter(
                        CRMWorkItem.status == "completed"
                    ).label("completed_count"),
                )
                .select_from(CRMWorkItem)
                .join(
                    CRMMarketingLearningReview,
                    (CRMMarketingLearningReview.tenant_id == CRMWorkItem.tenant_id)
                    & (CRMMarketingLearningReview.id == CRMWorkItem.source_learning_review_id),
                )
                .where(
                    CRMWorkItem.tenant_id == context.access.tenant_id,
                    CRMWorkItem.organization_unit_id == plan.organization_unit_id,
                    CRMWorkItem.campaign_id == plan.campaign_id,
                    CRMMarketingLearningReview.target_plan_id == plan.id,
                )
            )).one()
            open_learning_action_count = int(action_counts.open_count or 0)
            overdue_learning_action_count = int(action_counts.overdue_count or 0)
            unassigned_learning_action_count = int(action_counts.unassigned_count or 0)
            completed_learning_action_count = int(action_counts.completed_count or 0)
            tracked_learning_action_count = (
                open_learning_action_count + completed_learning_action_count
            )
            if tracked_learning_action_count:
                learning_action_completion_rate_percent = (
                    Decimal(completed_learning_action_count) * Decimal("100")
                    / Decimal(tracked_learning_action_count)
                ).quantize(Decimal("0.01"))
        items.append(CampaignPortfolioDecisionItem(
            campaign_id=plan.campaign_id,
            campaign_name=campaign_name,
            organization_unit_id=plan.organization_unit_id,
            target_plan_id=plan.id,
            period_start=plan.period_start,
            period_end=plan.period_end,
            status="review_required" if reasons else "on_track_or_insufficient_signal",
            attention_reasons=reasons,
            missed_metric_count=missed,
            no_data_metric_count=no_data,
            recorded_day_coverage_percent=coverage,
            measurement_record_count=len(measurements),
            latest_measurement_date=max(
                (row.measured_on for row in measurements), default=None
            ),
            metrics=queue_target_metrics,
            commerce_outcomes_by_currency=queue_commerce_metrics,
            commerce_data_status=(
                "observed"
                if queue_commerce_metrics
                else "no_linked_events"
                if plan.organization_unit_id in commerce_allowed_units
                else "not_authorized"
            ),
            planned_learning_review_count=review_counts.get("planned", 0),
            evaluated_learning_review_count=review_counts.get("evaluated", 0),
            open_learning_action_count=open_learning_action_count,
            overdue_learning_action_count=overdue_learning_action_count,
            unassigned_learning_action_count=unassigned_learning_action_count,
            completed_learning_action_count=completed_learning_action_count,
            tracked_learning_action_count=tracked_learning_action_count,
            learning_action_completion_rate_percent=learning_action_completion_rate_percent,
        ))
    items.sort(key=lambda item: (
        not bool(item.attention_reasons), -len(item.attention_reasons),
        item.period_end, item.campaign_name, str(item.target_plan_id),
    ))
    if status is not None:
        items = [item for item in items if item.status == status]
    if attention_reason is not None:
        items = [
            item for item in items
            if attention_reason in item.attention_reasons
        ]
    if metric_key is not None:
        items = [item for item in items if metric_key in item.metrics]
    if metric_status is not None:
        if metric_key is not None:
            items = [
                item for item in items
                if item.metrics[metric_key].status == metric_status
            ]
        else:
            items = [
                item for item in items
                if any(metric.status == metric_status for metric in item.metrics.values())
            ]
    summary_status_counts = {
        queue_status: sum(1 for item in items if item.status == queue_status)
        for queue_status in ("review_required", "on_track_or_insufficient_signal")
    }
    summary_attention_reason_counts: dict[str, int] = {}
    summary_metric_status_counts: dict[str, dict[str, int]] = {}
    for item in items:
        for reason in item.attention_reasons:
            summary_attention_reason_counts[reason] = (
                summary_attention_reason_counts.get(reason, 0) + 1
            )
        for key, metric in item.metrics.items():
            outcome_counts = summary_metric_status_counts.setdefault(
                key, {"met": 0, "not_met": 0, "no_data": 0}
            )
            outcome_counts[metric.status] += 1
    filtered_total = len(items)
    financial_by_currency: dict[str, dict[str, object]] = {}
    selected_windows = [
        item for item in items
    ]
    if selected_windows:
        spend_windows = [
            and_(
                CRMMarketingCampaignMeasurement.campaign_id == item.campaign_id,
                CRMMarketingCampaignMeasurement.organization_unit_id == item.organization_unit_id,
                CRMMarketingCampaignMeasurement.measured_on >= item.period_start,
                CRMMarketingCampaignMeasurement.measured_on <= item.period_end,
            )
            for item in selected_windows
        ]
        spend_rows = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                or_(*spend_windows),
                CRMMarketingCampaignMeasurement.actual_spend_amount.is_not(None),
                CRMMarketingCampaignMeasurement.actual_spend_currency.is_not(None),
            )
        )).all()
        for row in spend_rows:
            state = financial_by_currency.setdefault(
                row.actual_spend_currency,
                {
                    "spend_measurement_count": 0,
                    "recorded_spend_amount": Decimal("0"),
                    "paid_event_count": 0,
                    "paid_order_count": 0,
                    "paid_amount": Decimal("0"),
                    "refund_event_count": 0,
                    "refunded_order_count": 0,
                    "refunded_amount": Decimal("0"),
                },
            )
            state["spend_measurement_count"] += 1
            state["recorded_spend_amount"] += row.actual_spend_amount

    authorized_windows = [
        item for item in items
        if item.organization_unit_id in commerce_allowed_units
    ]
    source_product_financials: dict[tuple[str, str], dict[str, object]] = {}
    if authorized_windows:
        commerce_windows = [
            and_(
                CRMProductCommerceEvent.campaign_id == item.campaign_id,
                CRMProductCommerceEvent.organization_unit_id == item.organization_unit_id,
                CRMProductCommerceEvent.occurred_at >= datetime.combine(
                    item.period_start, time.min, tzinfo=timezone.utc
                ),
                CRMProductCommerceEvent.occurred_at < datetime.combine(
                    item.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc
                ),
            )
            for item in authorized_windows
        ]
        events = (await context.session.scalars(
            select(CRMProductCommerceEvent).where(
                CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                or_(*commerce_windows),
            )
        )).all()
        order_references: dict[tuple[str, str], dict[str, set[tuple[str, str]]]] = {}
        for event in events:
            state = financial_by_currency.setdefault(
                event.currency,
                {
                    "spend_measurement_count": 0,
                    "recorded_spend_amount": Decimal("0"),
                    "paid_event_count": 0,
                    "paid_order_count": 0,
                    "paid_amount": Decimal("0"),
                    "refund_event_count": 0,
                    "refunded_order_count": 0,
                    "refunded_amount": Decimal("0"),
                },
            )
            source_state = source_product_financials.setdefault(
                (event.source_product, event.currency),
                {
                    "paid_event_count": 0, "paid_amount": Decimal("0"),
                    "refund_event_count": 0, "refunded_amount": Decimal("0"),
                },
            )
            kinds = order_references.setdefault(
                (event.source_product, event.currency),
                {"paid": set(), "refunded": set()},
            )
            if event.event_kind == "paid":
                state["paid_event_count"] += 1
                state["paid_amount"] += event.amount
                source_state["paid_event_count"] += 1
                source_state["paid_amount"] += event.amount
                kinds["paid"].add((event.source_product, event.order_reference))
            else:
                state["refund_event_count"] += 1
                state["refunded_amount"] += event.amount
                source_state["refund_event_count"] += 1
                source_state["refunded_amount"] += event.amount
                kinds["refunded"].add((event.source_product, event.order_reference))
        for (source_product, currency), kinds in order_references.items():
            paid_orders = len(kinds["paid"])
            refunded_orders = len(kinds["refunded"])
            source_product_financials[(source_product, currency)]["paid_order_count"] = paid_orders
            source_product_financials[(source_product, currency)]["refunded_order_count"] = refunded_orders
            financial_by_currency[currency]["paid_order_count"] += paid_orders
            financial_by_currency[currency]["refunded_order_count"] += refunded_orders

    source_product_outcomes = []
    for (source_product, currency), state in sorted(source_product_financials.items()):
        currency_total = financial_by_currency[currency]
        total_paid = currency_total["paid_amount"]
        total_refunded = currency_total["refunded_amount"]
        paid_amount = state["paid_amount"]
        refunded_amount = state["refunded_amount"]
        source_product_outcomes.append(CampaignPortfolioSourceProductOutcome(
            source_product=source_product,
            currency=currency,
            paid_event_count=int(state["paid_event_count"]),
            paid_order_count=int(state["paid_order_count"]),
            paid_amount=paid_amount,
            paid_amount_share_percent=(
                (paid_amount * Decimal("100") / total_paid).quantize(Decimal("0.01"))
                if total_paid else None
            ),
            refund_event_count=int(state["refund_event_count"]),
            refunded_order_count=int(state["refunded_order_count"]),
            refunded_amount=refunded_amount,
            refunded_amount_share_percent=(
                (refunded_amount * Decimal("100") / total_refunded).quantize(Decimal("0.01"))
                if total_refunded else None
            ),
            net_paid_amount=paid_amount - refunded_amount,
        ))

    authorized_window_count = len(authorized_windows)
    commerce_scope_status = (
        "not_authorized"
        if not authorized_window_count
        else "partial"
        if authorized_window_count < len(items)
        else "complete"
    )
    financial_outcomes = [
        CampaignPortfolioCurrencyOutcome(
            currency=currency,
            spend_measurement_count=int(state["spend_measurement_count"]),
            recorded_spend_amount=state["recorded_spend_amount"],
            paid_event_count=int(state["paid_event_count"]),
            paid_order_count=int(state["paid_order_count"]),
            paid_amount=state["paid_amount"],
            refund_event_count=int(state["refund_event_count"]),
            refunded_order_count=int(state["refunded_order_count"]),
            refunded_amount=state["refunded_amount"],
            net_paid_amount=state["paid_amount"] - state["refunded_amount"],
        )
        for currency, state in sorted(financial_by_currency.items())
    ]
    summary = CampaignDecisionQueueSummary(
        total_count=filtered_total,
        campaign_count=len({item.campaign_id for item in items}),
        status_counts=summary_status_counts,
        attention_reason_counts=summary_attention_reason_counts,
        metric_status_counts=summary_metric_status_counts,
        financial_period_basis=(
            "Unique measurement and commerce records inside the union of the filtered "
            "target-plan date windows; totals are separated by currency."
        ),
        commerce_scope_status=commerce_scope_status,
        financial_outcomes_by_currency=financial_outcomes,
        source_product_outcomes=source_product_outcomes,
    )
    page_items = items[offset:offset + limit]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_campaign.decision_queue_viewed",
        target_type="crm_campaign_decision_queue",
        target_key=str(organization_unit_id or context.access.tenant_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={"period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
                     "candidate_count": total, "total_count": filtered_total,
                     "returned_count": len(page_items), "status_filter": status,
                     "attention_reason_filter": attention_reason,
                     "metric_key_filter": metric_key,
                     "metric_status_filter": metric_status,
                     "offset": offset, "limit": limit},
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignPortfolioDecisionQueue(
        summary=summary,
        generated_at=datetime.now(timezone.utc),
        period_start=period_start,
        period_end=period_end,
        items=page_items,
        total_count=filtered_total,
        has_more=offset + len(page_items) < filtered_total,
        basis=("Target plan evaluations, recorded-day coverage, and linked paid/refunded outcomes by "
               "currency; no causal attribution, source-specific spend allocation, or automatic action is applied."),
        automatic_recommendation_issued=False,
    )


def _spreadsheet_safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.get(
    "/portfolio-period-comparison",
    response_model=CampaignPortfolioPeriodComparison,
    operation_id="getCRMCampaignPortfolioPeriodComparison",
)
async def get_campaign_portfolio_period_comparison(
    baseline_start: date = Query(...),
    baseline_end: date = Query(...),
    comparison_start: date = Query(...),
    comparison_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignPortfolioPeriodComparison:
    """Compare recorded campaign outcomes across two non-overlapping periods."""
    if baseline_start > baseline_end or comparison_start > comparison_end:
        raise HTTPException(status_code=422, detail="Each period start must be on or before its end")
    if baseline_end >= comparison_start:
        raise HTTPException(status_code=422, detail="Baseline period must end before comparison period starts")
    if (baseline_end - baseline_start).days > 365 or (comparison_end - comparison_start).days > 365:
        raise HTTPException(status_code=422, detail="Each comparison period is limited to 366 calendar days")

    allowed_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.campaign:view")
    )).all())
    if organization_unit_id is not None:
        if organization_unit_id not in allowed_units:
            raise HTTPException(status_code=403, detail="Campaign period comparison is not authorized")
        allowed_units = {organization_unit_id}
    commerce_allowed_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.commerce_event:view")
    )).all())
    selected_commerce_units = allowed_units & commerce_allowed_units
    metric_keys = ("impressions", "clicks", "leads", "conversions")
    metric_columns = {
        key: getattr(CRMMarketingCampaignMeasurement, key) for key in metric_keys
    }

    async def measurement_snapshot(start: date, end: date) -> dict[str, object]:
        expressions = [
            func.sum(column).label(key)
            for key, column in metric_columns.items()
        ]
        expressions.extend(
            func.count(func.distinct(CRMMarketingCampaignMeasurement.measured_on))
            .filter(column.is_not(None))
            .label(f"{key}_days")
            for key, column in metric_columns.items()
        )
        expressions.extend((
            func.count(func.distinct(CRMMarketingCampaignMeasurement.measured_on))
            .filter(
                CRMMarketingCampaignMeasurement.impressions.is_not(None)
                & CRMMarketingCampaignMeasurement.clicks.is_not(None)
            )
            .label("click_through_rate_days"),
            func.count(func.distinct(CRMMarketingCampaignMeasurement.measured_on))
            .filter(
                CRMMarketingCampaignMeasurement.clicks.is_not(None)
                & CRMMarketingCampaignMeasurement.leads.is_not(None)
            )
            .label("click_to_lead_rate_days"),
            func.count(func.distinct(CRMMarketingCampaignMeasurement.measured_on))
            .filter(
                CRMMarketingCampaignMeasurement.leads.is_not(None)
                & CRMMarketingCampaignMeasurement.conversions.is_not(None)
            )
            .label("lead_to_conversion_rate_days"),
        ))
        expressions.extend((
            func.count(func.distinct(CRMMarketingCampaignMeasurement.campaign_id)).label("campaign_count"),
            func.count(CRMMarketingCampaignMeasurement.id).label("record_count"),
            func.count(func.distinct(CRMMarketingCampaignMeasurement.measured_on)).label("recorded_days"),
        ))
        row = (await context.session.execute(
            select(*expressions).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id.in_(allowed_units),
                CRMMarketingCampaignMeasurement.measured_on >= start,
                CRMMarketingCampaignMeasurement.measured_on <= end,
            )
        )).one()
        snapshot = dict(row._mapping)
        for key in metric_keys:
            if snapshot[key] is not None:
                snapshot[key] = int(snapshot[key])
        return snapshot

    baseline = await measurement_snapshot(baseline_start, baseline_end)
    comparison = await measurement_snapshot(comparison_start, comparison_end)
    metric_comparisons: dict[str, PeriodMetricComparison] = {}
    for key in metric_keys:
        before = baseline[key]
        after = comparison[key]
        change = after - before if before is not None and after is not None else None
        change_percent = (
            (Decimal(str(change)) * Decimal("100") / Decimal(str(before))).quantize(Decimal("0.01"))
            if before not in (None, 0) and after is not None
            else None
        )
        metric_comparisons[key] = PeriodMetricComparison(
            baseline_value=before,
            comparison_value=after,
            change=change,
            change_percent=change_percent,
            value_unit="count",
            change_unit="count",
            baseline_observed_days=int(baseline[f"{key}_days"] or 0),
            comparison_observed_days=int(comparison[f"{key}_days"] or 0),
        )

    for rate_key, numerator_key, denominator_key in (
        ("click_through_rate", "clicks", "impressions"),
        ("click_to_lead_rate", "leads", "clicks"),
        ("lead_to_conversion_rate", "conversions", "leads"),
    ):
        before_denominator = baseline[denominator_key]
        after_denominator = comparison[denominator_key]
        before_rate = (
            (Decimal(baseline[numerator_key]) * Decimal("100")
             / Decimal(before_denominator)).quantize(Decimal("0.01"))
            if baseline[numerator_key] is not None
            and before_denominator is not None
            and before_denominator > 0
            else None
        )
        after_rate = (
            (Decimal(comparison[numerator_key]) * Decimal("100")
             / Decimal(after_denominator)).quantize(Decimal("0.01"))
            if comparison[numerator_key] is not None
            and after_denominator is not None
            and after_denominator > 0
            else None
        )
        rate_change = (
            (after_rate - before_rate).quantize(Decimal("0.01"))
            if before_rate is not None and after_rate is not None
            else None
        )
        rate_change_percent = (
            (rate_change * Decimal("100") / before_rate).quantize(Decimal("0.01"))
            if before_rate not in (None, Decimal("0")) and rate_change is not None
            else None
        )
        metric_comparisons[rate_key] = PeriodMetricComparison(
            baseline_value=before_rate,
            comparison_value=after_rate,
            change=rate_change,
            change_percent=rate_change_percent,
            value_unit="percent",
            change_unit="percentage_points",
            baseline_observed_days=int(baseline[f"{rate_key}_days"] or 0),
            comparison_observed_days=int(comparison[f"{rate_key}_days"] or 0),
        )

    currency_values: dict[str, dict[str, Decimal]] = {}
    period_ranges = (
        ("baseline", baseline_start, baseline_end),
        ("comparison", comparison_start, comparison_end),
    )
    for prefix, start, end in period_ranges:
        spend_rows = (await context.session.execute(
            select(
                CRMMarketingCampaignMeasurement.actual_spend_currency,
                func.sum(CRMMarketingCampaignMeasurement.actual_spend_amount).label("amount"),
            )
            .where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id.in_(allowed_units),
                CRMMarketingCampaignMeasurement.measured_on >= start,
                CRMMarketingCampaignMeasurement.measured_on <= end,
                CRMMarketingCampaignMeasurement.actual_spend_amount.is_not(None),
                CRMMarketingCampaignMeasurement.actual_spend_currency.is_not(None),
            )
            .group_by(CRMMarketingCampaignMeasurement.actual_spend_currency)
        )).all()
        for row in spend_rows:
            state = currency_values.setdefault(row.actual_spend_currency, {})
            state[f"{prefix}_spend"] = row.amount or Decimal("0")
        if selected_commerce_units:
            event_start = datetime.combine(start, time.min, tzinfo=timezone.utc)
            event_end = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
            event_rows = (await context.session.execute(
                select(
                    CRMProductCommerceEvent.currency,
                    CRMProductCommerceEvent.event_kind,
                    func.sum(CRMProductCommerceEvent.amount).label("amount"),
                )
                .where(
                    CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                    CRMProductCommerceEvent.organization_unit_id.in_(selected_commerce_units),
                    CRMProductCommerceEvent.occurred_at >= event_start,
                    CRMProductCommerceEvent.occurred_at < event_end,
                    CRMProductCommerceEvent.campaign_id.is_not(None),
                )
                .group_by(
                    CRMProductCommerceEvent.currency,
                    CRMProductCommerceEvent.event_kind,
                )
            )).all()
            for row in event_rows:
                state = currency_values.setdefault(row.currency, {})
                state[f"{prefix}_{row.event_kind}"] = row.amount or Decimal("0")

    financial_outcomes = []
    for currency, state in sorted(currency_values.items()):
        baseline_spend = state.get("baseline_spend", Decimal("0"))
        comparison_spend = state.get("comparison_spend", Decimal("0"))
        baseline_paid = state.get("baseline_paid", Decimal("0"))
        comparison_paid = state.get("comparison_paid", Decimal("0"))
        baseline_refunded = state.get("baseline_refunded", Decimal("0"))
        comparison_refunded = state.get("comparison_refunded", Decimal("0"))
        financial_outcomes.append(PeriodCurrencyComparison(
            currency=currency,
            baseline_spend_amount=baseline_spend,
            comparison_spend_amount=comparison_spend,
            baseline_paid_amount=baseline_paid,
            comparison_paid_amount=comparison_paid,
            baseline_refunded_amount=baseline_refunded,
            comparison_refunded_amount=comparison_refunded,
            baseline_net_paid_amount=baseline_paid - baseline_refunded,
            comparison_net_paid_amount=comparison_paid - comparison_refunded,
        ))

    authorized_scope_count = len(selected_commerce_units)
    commerce_scope_status = (
        "not_authorized"
        if not authorized_scope_count
        else "partial"
        if authorized_scope_count < len(allowed_units)
        else "complete"
    )
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_campaign.period_comparison_viewed",
        target_type="crm_campaign_portfolio_period_comparison",
        target_key=str(organization_unit_id or context.access.tenant_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "baseline_start": baseline_start.isoformat(),
            "baseline_end": baseline_end.isoformat(),
            "comparison_start": comparison_start.isoformat(),
            "comparison_end": comparison_end.isoformat(),
            "baseline_campaign_count": int(baseline["campaign_count"] or 0),
            "comparison_campaign_count": int(comparison["campaign_count"] or 0),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignPortfolioPeriodComparison(
        generated_at=datetime.now(timezone.utc),
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        comparison_start=comparison_start,
        comparison_end=comparison_end,
        baseline_calendar_days=(baseline_end - baseline_start).days + 1,
        comparison_calendar_days=(comparison_end - comparison_start).days + 1,
        baseline_campaign_count=int(baseline["campaign_count"] or 0),
        comparison_campaign_count=int(comparison["campaign_count"] or 0),
        baseline_measurement_record_count=int(baseline["record_count"] or 0),
        comparison_measurement_record_count=int(comparison["record_count"] or 0),
        baseline_recorded_days=int(baseline["recorded_days"] or 0),
        comparison_recorded_days=int(comparison["recorded_days"] or 0),
        metrics=metric_comparisons,
        financial_outcomes_by_currency=financial_outcomes,
        commerce_scope_status=commerce_scope_status,
        interpretation=(
            "Observed totals and period-over-period changes are descriptive. "
            "They do not establish causal attribution, normalize for campaign mix, "
            "or issue an automatic recommendation. A percentage change is omitted "
            "when the baseline metric is zero or unavailable."
        ),
    )


@router.get(
    "/decision-queue/export.csv",
    response_class=Response,
    operation_id="exportCRMCampaignPortfolioDecisionQueueCsv",
)
async def export_campaign_portfolio_decision_queue_csv(
    period_start: date = Query(...),
    period_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    status: Literal["review_required", "on_track_or_insufficient_signal"] | None = Query(default=None),
    attention_reason: Literal[
        "target_missed",
        "net_commerce_target_missed",
        "target_metrics_without_data",
        "net_commerce_target_without_data",
        "low_recorded_day_coverage",
    ] | None = Query(default=None),
    metric_key: Literal[
        "impressions", "clicks", "leads", "conversions", "spend",
        "cost_per_lead", "cost_per_conversion", "period_net_paid_to_spend",
    ] | None = Query(default=None),
    metric_status: Literal["met", "not_met", "no_data"] | None = Query(default=None),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    """Export the complete filtered decision queue for spreadsheet analysis."""
    queue = await get_campaign_portfolio_decision_queue(
        period_start=period_start,
        period_end=period_end,
        organization_unit_id=organization_unit_id,
        status=status,
        attention_reason=attention_reason,
        metric_key=metric_key,
        metric_status=metric_status,
        limit=5001,
        offset=0,
        context=context,
    )
    if queue.total_count > 5000:
        raise HTTPException(
            status_code=422,
            detail="CSV export is limited to 5000 plans; narrow the period or filters",
        )

    metric_keys = sorted({key for item in queue.items for key in item.metrics})
    headers = [
        "campaign_name", "campaign_id", "organization_unit_id", "target_plan_id",
        "period_start", "period_end", "status", "attention_reasons",
        "missed_metric_count", "no_data_metric_count",
        "recorded_day_coverage_percent", "measurement_record_count",
        "latest_measurement_date", "commerce_data_status",
        "commerce_outcomes_by_currency", "planned_learning_review_count",
        "evaluated_learning_review_count", "open_learning_action_count",
        "overdue_learning_action_count", "unassigned_learning_action_count",
        "completed_learning_action_count", "tracked_learning_action_count",
        "learning_action_completion_rate_percent",
    ]
    for key in metric_keys:
        headers.extend((
            f"metric_{key}_target", f"metric_{key}_actual",
            f"metric_{key}_status", f"metric_{key}_currency",
            f"metric_{key}_coverage_percent",
        ))

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for item in queue.items:
        values: list[object] = [
            item.campaign_name, item.campaign_id, item.organization_unit_id,
            item.target_plan_id, item.period_start, item.period_end, item.status,
            "|".join(item.attention_reasons), item.missed_metric_count,
            item.no_data_metric_count, item.recorded_day_coverage_percent,
            item.measurement_record_count, item.latest_measurement_date,
            item.commerce_data_status,
            json.dumps(
                [row.model_dump(mode="json") for row in item.commerce_outcomes_by_currency],
                ensure_ascii=False, separators=(",", ":"),
            ),
            item.planned_learning_review_count, item.evaluated_learning_review_count,
            item.open_learning_action_count, item.overdue_learning_action_count,
            item.unassigned_learning_action_count, item.completed_learning_action_count,
            item.tracked_learning_action_count,
            item.learning_action_completion_rate_percent,
        ]
        for key in metric_keys:
            metric = item.metrics.get(key)
            values.extend((
                metric.target if metric else None,
                metric.actual if metric else None,
                metric.status if metric else None,
                metric.currency if metric else None,
                metric.recorded_day_coverage_percent if metric else None,
            ))
        writer.writerow([_spreadsheet_safe_cell(value) for value in values])

    filename = f"campaign-decision-queue-{period_start}-{period_end}.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{campaign_id}/decision-workspace/{target_id}",
    response_model=CampaignDecisionWorkspace,
    operation_id="getCRMCampaignDecisionWorkspace",
)
async def get_campaign_decision_workspace(
    campaign_id: UUID,
    target_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignDecisionWorkspace:
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="CRM campaign not found")
    for permission in ("crm.campaign:view", "crm.commerce_event:view"):
        if not await has_crm_permission(
            context,
            permission_key=permission,
            organization_unit_id=campaign.organization_unit_id,
        ):
            raise HTTPException(status_code=403, detail="Campaign decision workspace is not authorized")

    plan = await context.session.scalar(
        select(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignTargetPlan.campaign_id == campaign.id,
            CRMMarketingCampaignTargetPlan.id == target_id,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Campaign target plan not found")

    measurements = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign.id,
            CRMMarketingCampaignMeasurement.measured_on >= plan.period_start,
            CRMMarketingCampaignMeasurement.measured_on <= plan.period_end,
        ).order_by(CRMMarketingCampaignMeasurement.measured_on)
    )).all()
    period_days = (plan.period_end - plan.period_start).days + 1
    raw_metrics = evaluate_plan_metrics(plan, list(measurements))
    raw_metrics.pop("roas", None)

    metrics: dict[str, DecisionMetric] = {}
    for key, result in raw_metrics.items():
        observed_days = result.observed_days
        basis = (
            "Sum of non-null daily CRM campaign measurements."
            if key in {"impressions", "clicks", "leads", "conversions"}
            else "Currency-compatible campaign spend and outcome values on the same recorded days."
        )
        if result.actual is None:
            explanation = "No compatible recorded value is available for this target period."
        elif result.status == "met":
            explanation = "The recorded value meets the target; read it together with recorded-day coverage."
        else:
            explanation = "The recorded value does not meet the target; read it together with recorded-day coverage."
        metrics[key] = DecisionMetric(
            target=result.target,
            actual=result.actual,
            status=result.status,
            currency=result.currency,
            observed_days=observed_days,
            paired_days=result.paired_days,
            period_days=period_days,
            recorded_day_coverage_percent=_coverage_percent(observed_days, period_days),
            basis=basis,
            explanation=explanation,
        )

    event_start = datetime.combine(plan.period_start, time.min, tzinfo=timezone.utc)
    event_end = datetime.combine(
        plan.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    commerce_rows = (await context.session.execute(
        select(
            CRMProductCommerceEvent.currency,
            CRMProductCommerceEvent.event_kind,
            func.count(CRMProductCommerceEvent.id).label("event_count"),
            func.count(func.distinct(tuple_(
                CRMProductCommerceEvent.source_product,
                CRMProductCommerceEvent.order_reference,
            ))).label("order_count"),
            func.sum(CRMProductCommerceEvent.amount).label("amount_total"),
        )
        .where(
            CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
            CRMProductCommerceEvent.organization_unit_id == campaign.organization_unit_id,
            CRMProductCommerceEvent.campaign_id == campaign.id,
            CRMProductCommerceEvent.occurred_at >= event_start,
            CRMProductCommerceEvent.occurred_at < event_end,
        )
        .group_by(
            CRMProductCommerceEvent.currency,
            CRMProductCommerceEvent.event_kind,
        )
    )).all()

    source_commerce_rows = (await context.session.execute(
        select(
            CRMProductCommerceEvent.source_product,
            CRMProductCommerceEvent.currency,
            CRMProductCommerceEvent.event_kind,
            func.count(CRMProductCommerceEvent.id).label("event_count"),
            func.count(func.distinct(CRMProductCommerceEvent.order_reference)).label("order_count"),
            func.sum(CRMProductCommerceEvent.amount).label("amount_total"),
        )
        .where(
            CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
            CRMProductCommerceEvent.organization_unit_id == campaign.organization_unit_id,
            CRMProductCommerceEvent.campaign_id == campaign.id,
            CRMProductCommerceEvent.occurred_at >= event_start,
            CRMProductCommerceEvent.occurred_at < event_end,
        )
        .group_by(
            CRMProductCommerceEvent.source_product,
            CRMProductCommerceEvent.currency,
            CRMProductCommerceEvent.event_kind,
        )
        .order_by(
            CRMProductCommerceEvent.source_product,
            CRMProductCommerceEvent.currency,
        )
    )).all()

    source_outcomes: dict[tuple[str, str], dict[str, object]] = {}
    for row in source_commerce_rows:
        state = source_outcomes.setdefault(
            (row.source_product, row.currency),
            {
                "paid_event_count": 0, "paid_order_count": 0,
                "paid_amount": Decimal("0"), "refund_event_count": 0,
                "refunded_order_count": 0, "refunded_amount": Decimal("0"),
            },
        )
        if row.event_kind == "paid":
            state["paid_event_count"] = int(row.event_count)
            state["paid_order_count"] = int(row.order_count)
            state["paid_amount"] = row.amount_total or Decimal("0")
        else:
            state["refund_event_count"] = int(row.event_count)
            state["refunded_order_count"] = int(row.order_count)
            state["refunded_amount"] = row.amount_total or Decimal("0")

    source_metrics = []
    for (source_product, currency), state in sorted(source_outcomes.items()):
        paid_amount = state["paid_amount"]
        refunded_amount = state["refunded_amount"]
        paid_order_count = int(state["paid_order_count"])
        net_paid_amount = paid_amount - refunded_amount
        source_metrics.append(DecisionCommerceSourceOutcome(
            source_product=source_product,
            currency=currency,
            paid_event_count=int(state["paid_event_count"]),
            paid_order_count=paid_order_count,
            paid_amount=paid_amount,
            refund_event_count=int(state["refund_event_count"]),
            refunded_order_count=int(state["refunded_order_count"]),
            refunded_amount=refunded_amount,
            net_paid_amount=net_paid_amount,
            net_paid_amount_per_paid_order=(
                (net_paid_amount / Decimal(paid_order_count)).quantize(Decimal("0.000001"))
                if paid_order_count else None
            ),
        ))

    spend_by_currency: dict[str, tuple[Decimal, int]] = {}
    for row in measurements:
        if row.actual_spend_amount is None or row.actual_spend_currency is None:
            continue
        amount, days = spend_by_currency.get(
            row.actual_spend_currency, (Decimal("0"), 0)
        )
        spend_by_currency[row.actual_spend_currency] = (
            amount + row.actual_spend_amount,
            days + 1,
        )

    commerce_by_currency: dict[str, dict[str, object]] = {}
    for row in commerce_rows:
        state = commerce_by_currency.setdefault(
            row.currency,
            {
                "paid_event_count": 0,
                "paid_order_count": 0,
                "paid_amount": Decimal("0"),
                "refund_event_count": 0,
                "refunded_order_count": 0,
                "refunded_amount": Decimal("0"),
            },
        )
        if row.event_kind == "paid":
            state["paid_event_count"] = int(row.event_count)
            state["paid_order_count"] = int(row.order_count)
            state["paid_amount"] = row.amount_total or Decimal("0")
        else:
            state["refund_event_count"] = int(row.event_count)
            state["refunded_order_count"] = int(row.order_count)
            state["refunded_amount"] = row.amount_total or Decimal("0")

    currency_metrics = []
    for currency in sorted(set(spend_by_currency) | set(commerce_by_currency)):
        spend_info = spend_by_currency.get(currency)
        spend = spend_info[0] if spend_info is not None else None
        state = commerce_by_currency.get(currency, {})
        paid_amount = state.get("paid_amount", Decimal("0"))
        refunded_amount = state.get("refunded_amount", Decimal("0"))
        net_paid_amount = paid_amount - refunded_amount
        paid_order_count = state.get("paid_order_count", 0)
        paid_count = state.get("paid_event_count", 0)
        ratio = (
            (paid_amount / spend).quantize(Decimal("0.000001"))
            if paid_count and spend is not None and spend > 0
            else None
        )
        currency_metrics.append(DecisionCommerceCurrency(
            currency=currency,
            spend_amount=spend,
            spend_observed_days=spend_info[1] if spend_info is not None else 0,
            paid_event_count=paid_count,
            paid_order_count=paid_order_count,
            paid_amount=paid_amount,
            net_paid_amount=net_paid_amount,
            net_paid_amount_per_paid_order=(
                (net_paid_amount / Decimal(paid_order_count)).quantize(Decimal("0.000001"))
                if paid_order_count else None
            ),
            refund_event_count=state.get("refund_event_count", 0),
            refunded_order_count=state.get("refunded_order_count", 0),
            refunded_amount=refunded_amount,
            observed_paid_to_spend_multiple=ratio,
            observed_net_paid_to_spend_multiple=(
                (net_paid_amount / spend).quantize(Decimal("0.000001"))
                if paid_count and spend is not None and spend > 0
                else None
            ),
        ))

    if plan.min_net_paid_to_spend is not None:
        currency = plan.net_paid_to_spend_currency
        spend_info = spend_by_currency.get(currency)
        spend = spend_info[0] if spend_info is not None else None
        outcome = commerce_by_currency.get(currency, {})
        paid_count = int(outcome.get("paid_event_count", 0))
        net_paid = outcome.get("paid_amount", Decimal("0")) - outcome.get("refunded_amount", Decimal("0"))
        actual = (
            (net_paid / spend).quantize(Decimal("0.000001"))
            if paid_count and spend is not None and spend > 0
            else None
        )
        metrics["period_net_paid_to_spend"] = DecisionMetric(
            target=plan.min_net_paid_to_spend,
            actual=actual,
            status=_status(plan.min_net_paid_to_spend, actual, at_least=True),
            currency=currency,
            observed_days=spend_info[1] if spend_info is not None else 0,
            paired_days=0,
            period_days=period_days,
            recorded_day_coverage_percent=_coverage_percent(
                spend_info[1] if spend_info is not None else 0, period_days
            ),
            basis=NET_COMMERCE_BASIS,
            explanation=(
                "No linked paid event and positive same-currency spend are both available."
                if actual is None
                else "Full-period net paid amount divided by recorded same-currency spend is compared with the manager-entered target."
            ),
        )

    if plan.min_roas is not None:
        currency = plan.roas_currency
        spend_info = spend_by_currency.get(currency)
        spend = spend_info[0] if spend_info is not None else None
        outcome = commerce_by_currency.get(currency, {})
        paid_count = int(outcome.get("paid_event_count", 0))
        paid_amount = outcome.get("paid_amount", Decimal("0"))
        actual = (
            (paid_amount / spend).quantize(Decimal("0.000001"))
            if paid_count and spend is not None and spend > 0
            else None
        )
        status = _status(plan.min_roas, actual, at_least=True)
        observed_days = spend_info[1] if spend_info is not None else 0
        metrics["paid_to_spend"] = DecisionMetric(
            target=plan.min_roas,
            actual=actual,
            status=status,
            currency=currency,
            observed_days=observed_days,
            paired_days=0,
            period_days=period_days,
            recorded_day_coverage_percent=_coverage_percent(observed_days, period_days),
            basis=ROAS_BASIS,
            explanation=(
                "No linked paid event and positive same-currency spend are both available."
                if actual is None
                else "Observed paid-to-spend value is compared with the plan target; refunds are shown separately."
            ),
        )

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_campaign.decision_workspace_viewed",
        target_type="crm_campaign_decision_workspace",
        target_key=str(plan.id),
        organization_unit_id=campaign.organization_unit_id,
        before_state=None,
        after_state={
            "campaign_id": str(campaign.id),
            "target_plan_id": str(plan.id),
            "period_start": plan.period_start.isoformat(),
            "period_end": plan.period_end.isoformat(),
            "measurement_record_count": len(measurements),
            "commerce_currency_bucket_count": len(currency_metrics),
        },
        correlation_id=None,
    ))
    await context.session.flush()

    metric_definitions: dict[str, MetricDefinition] = {}
    for metric_key in metrics:
        definition = get_metric_definition(metric_key)
        if definition is not None:
            metric_definitions[metric_key] = definition
    for metric_key in ("net_paid_amount", "net_paid_amount_per_paid_order", "period_net_paid_to_spend"):
        definition = get_metric_definition(metric_key)
        if definition is not None:
            metric_definitions[metric_key] = definition
    coverage_definition = get_metric_definition("recorded_day_coverage")
    assert coverage_definition is not None

    return CampaignDecisionWorkspace(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        organization_unit_id=campaign.organization_unit_id,
        period_start=plan.period_start,
        period_end=plan.period_end,
        generated_at=datetime.now(timezone.utc),
        target_plan=CampaignTargetRead.model_validate(plan),
        period_calendar_days=period_days,
        coverage_basis=(
            "Recorded-day coverage is observed measurement days divided by calendar days "
            "in the target period. It shows data presence, not channel reporting completeness."
        ),
        commerce_basis=NET_COMMERCE_BASIS,
        metrics=metrics,
        metric_definitions=metric_definitions,
        coverage_definition=coverage_definition,
        commerce_outcomes_by_currency=currency_metrics,
        commerce_outcomes_by_source_product=source_metrics,
        interpretation=(
            "Metrics support manager review and do not issue an automatic pause, continue, "
            "budget, or channel recommendation."
        ),
        causal_attribution_applied=False,
        automatic_recommendation_issued=False,
    )
