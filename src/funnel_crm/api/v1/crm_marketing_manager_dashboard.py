"""Unified read-only dashboard for marketing managers."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_campaign_measurements import (
    CampaignChannelPerformanceItem,
    CampaignEfficiencyMetrics,
    CampaignMetricCoverage,
    CampaignMeasurementQualityRead,
    CampaignSegmentPerformanceItem,
    _campaign_efficiency,
    get_campaign_channel_performance,
    get_campaign_measurement_quality,
    get_campaign_performance_portfolio,
    get_campaign_segment_performance,
)
from funnel_crm.api.v1.crm_campaign_target_analytics import (
    CampaignManagerSignal,
    CampaignTargetMetricVariance,
    PortfolioCommerceOutcome,
    PortfolioCommerceSourceOutcome,
    TargetOutcomeCounts,
    review_campaign_target_portfolio,
)
from funnel_crm.platform.models import AuditEvent
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/marketing-manager",
    tags=["CRM marketing analytics"],
)


class DashboardMetricCoverage(BaseModel):
    observed_days: int
    expected_days: int
    missing_days: int
    coverage_percent: Decimal | None


class DashboardPerformanceSummary(BaseModel):
    campaign_count: int
    measured_campaign_count: int
    truncated: bool
    totals: dict[str, int | None]
    planned_budget_by_currency: dict[str, Decimal]
    actual_spend_by_currency: dict[str, Decimal]
    attributed_revenue_by_currency: dict[str, Decimal]
    efficiency: CampaignEfficiencyMetrics


class DashboardDataQualitySummary(BaseModel):
    campaign_count: int
    campaigns_without_measurements: int
    expected_campaign_days: int
    covered_campaign_days: int
    missing_campaign_days: int
    out_of_schedule_measurement_days: int
    metric_coverage: dict[str, DashboardMetricCoverage]
    truncated: bool


class DashboardTargetSummary(BaseModel):
    campaign_count: int
    campaign_list_truncated: bool
    metric_outcomes: dict[str, TargetOutcomeCounts]
    metric_variances: dict[str, CampaignTargetMetricVariance]
    commerce_outcomes_by_currency: list[PortfolioCommerceOutcome]
    commerce_outcomes_by_source_product: list[PortfolioCommerceSourceOutcome]
    commerce_basis: str
    manager_signals: list[CampaignManagerSignal]
    manager_signals_truncated: bool
    manager_signals_basis: str


class MarketingManagerDashboardRead(BaseModel):
    period_start: date
    period_end: date
    performance: DashboardPerformanceSummary
    channel_performance: list[CampaignChannelPerformanceItem]
    segment_performance: list[CampaignSegmentPerformanceItem]
    data_quality: DashboardDataQualitySummary
    target_attainment: DashboardTargetSummary
    dashboard_basis: str


@router.get(
    "/campaigns",
    response_model=MarketingManagerDashboardRead,
    operation_id="getMarketingManagerCampaignDashboard",
    summary="Review campaign performance, target attainment, and data quality together",
)
async def get_marketing_manager_campaign_dashboard(
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> MarketingManagerDashboardRead:
    if period_start > period_end or (period_end - period_start).days > 365:
        raise HTTPException(
            status_code=422,
            detail="Dashboard period must be ordered and limited to 366 calendar days",
        )

    performance = await get_campaign_performance_portfolio(
        period_start=period_start, period_end=period_end, context=context
    )
    channels = await get_campaign_channel_performance(
        period_start=period_start, period_end=period_end, context=context
    )
    segments = await get_campaign_segment_performance(
        period_start=period_start, period_end=period_end, context=context
    )
    quality: CampaignMeasurementQualityRead = await get_campaign_measurement_quality(
        period_start=period_start, period_end=period_end, context=context
    )
    targets = await review_campaign_target_portfolio(
        period_start=period_start,
        period_end=period_end,
        context=context,
        organization_unit_id=None,
        grouped_by="channel",
        campaign_ids=None,
    )

    metric_keys = (
        "impressions", "reach", "clicks", "responses", "leads", "conversions",
        "assigned_count", "exposure_count", "return_count",
    )
    totals: dict[str, int | None] = {}
    for key in metric_keys:
        values = [
            item.totals[key]
            for item in performance.items
            if item.totals[key] is not None
        ]
        totals[key] = sum(values) if values else None

    def sum_currency(attribute: str) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for item in performance.items:
            for currency, amount in getattr(item, attribute).items():
                result[currency] = result.get(currency, Decimal("0")) + amount
        return result

    planned_budget: dict[str, Decimal] = {}
    for item in performance.items:
        if item.planned_budget_amount is not None and item.planned_budget_currency is not None:
            currency = item.planned_budget_currency
            planned_budget[currency] = (
                planned_budget.get(currency, Decimal("0")) + item.planned_budget_amount
            )
    spend = sum_currency("actual_spend_by_currency")
    revenue = sum_currency("attributed_revenue_by_currency")

    coverage_keys = metric_keys
    metric_coverage: dict[str, DashboardMetricCoverage] = {}
    for key in coverage_keys:
        observed = sum(item.metric_coverage[key].observed_days for item in quality.items)
        expected = sum(item.metric_coverage[key].expected_days for item in quality.items)
        metric_coverage[key] = DashboardMetricCoverage(
            observed_days=observed,
            expected_days=expected,
            missing_days=max(expected - observed, 0),
            coverage_percent=(
                (Decimal(observed) * Decimal("100") / Decimal(expected)).quantize(Decimal("0.01"))
                if expected > 0
                else None
            ),
        )

    manager_signals = targets.manager_signals[:50]
    target_summary = DashboardTargetSummary(
        campaign_count=targets.campaign_count,
        campaign_list_truncated=targets.campaign_list_truncated,
        metric_outcomes=targets.metric_outcomes,
        metric_variances=targets.metric_variances,
        commerce_outcomes_by_currency=targets.commerce_outcomes_by_currency,
        commerce_outcomes_by_source_product=targets.commerce_outcomes_by_source_product,
        commerce_basis=targets.commerce_basis,
        manager_signals=manager_signals,
        manager_signals_truncated=(
            targets.manager_signals_truncated
            or len(targets.manager_signals) > len(manager_signals)
        ),
        manager_signals_basis=targets.manager_signals_basis,
    )

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.campaign_dashboard.viewed",
        target_type="crm_marketing_manager_campaign_dashboard",
        target_key=f"{period_start.isoformat()}:{period_end.isoformat()}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "campaign_count": performance.campaign_count,
            "campaigns_with_measurements": performance.measured_campaign_count,
            "target_campaign_count": targets.campaign_count,
            "missing_campaign_days": quality.missing_campaign_days,
        },
        correlation_id=None,
    ))
    await context.session.flush()

    return MarketingManagerDashboardRead(
        period_start=period_start,
        period_end=period_end,
        performance=DashboardPerformanceSummary(
            campaign_count=performance.campaign_count,
            measured_campaign_count=performance.measured_campaign_count,
            truncated=performance.truncated,
            totals=totals,
            planned_budget_by_currency=planned_budget,
            actual_spend_by_currency=spend,
            attributed_revenue_by_currency=revenue,
            efficiency=_campaign_efficiency(spend, revenue),
        ),
        channel_performance=channels.items,
        segment_performance=segments.items,
        data_quality=DashboardDataQualitySummary(
            campaign_count=quality.campaign_count,
            campaigns_without_measurements=quality.campaigns_without_measurements,
            expected_campaign_days=quality.expected_campaign_days,
            covered_campaign_days=quality.covered_campaign_days,
            missing_campaign_days=quality.missing_campaign_days,
            out_of_schedule_measurement_days=quality.out_of_schedule_measurement_days,
            metric_coverage=metric_coverage,
            truncated=quality.truncated,
        ),
        target_attainment=target_summary,
        dashboard_basis=(
            "The dashboard composes authorized CRM campaign reports for one date range. "
            "Currency totals remain separate; target and measurement gaps are descriptive, "
            "and reported relationships do not establish causality."
        ),
    )
