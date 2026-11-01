"""Unified read-only dashboard for marketing managers."""

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from io import StringIO
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, text
from pydantic import BaseModel, Field, field_validator

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
from funnel_crm.platform.models import AuditEvent, CRMMarketingCampaign
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/marketing-manager",
    tags=["CRM marketing analytics"],
)




class CampaignBudgetPacingItem(BaseModel):
    campaign_id: UUID
    campaign_name: str
    campaign_status: str
    period_start: date
    as_of: date
    planned_budget_amount: Decimal | None
    budget_currency: str | None
    actual_spend_in_budget_currency: Decimal | None
    expected_spend_to_date: Decimal | None
    variance_from_expected: Decimal | None
    variance_percent: float | None
    spend_in_other_currencies: dict[str, Decimal]
    scheduled_days_elapsed: int | None
    scheduled_days_total: int | None
    pacing_status: str


class CampaignBudgetPacingRead(BaseModel):
    period_start: date
    as_of: date
    campaign_count: int
    items: list[CampaignBudgetPacingItem]
    truncated: bool
    pacing_basis: str


@router.get(
    "/campaigns/budget-pacing",
    response_model=CampaignBudgetPacingRead,
    operation_id="getMarketingManagerCampaignBudgetPacing",
    summary="Compare observed campaign spend with linear scheduled budget pacing",
)
async def get_marketing_manager_campaign_budget_pacing(
    period_start: date = Query(...),
    as_of: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignBudgetPacingRead:
    if period_start > as_of:
        raise HTTPException(status_code=422, detail="period_start must not be after as_of")
    if (as_of - period_start).days > 365:
        raise HTTPException(
            status_code=422,
            detail="Budget pacing windows are limited to 366 calendar days",
        )
    portfolio = await get_campaign_performance_portfolio(
        period_start=period_start, period_end=as_of, context=context
    )
    campaign_ids = [item.campaign_id for item in portfolio.items]
    campaigns: dict[UUID, CRMMarketingCampaign] = {}
    if campaign_ids:
        rows = await context.session.scalars(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == context.access.tenant_id,
                CRMMarketingCampaign.id.in_(campaign_ids),
            )
        )
        campaigns = {campaign.id: campaign for campaign in rows}

    items: list[CampaignBudgetPacingItem] = []
    pacing_counts = {
        "ahead_of_pace": 0,
        "behind_pace": 0,
        "on_pace": 0,
        "not_started": 0,
        "no_budget": 0,
        "schedule_incomplete": 0,
        "no_spend_data": 0,
    }
    for performance in portfolio.items:
        campaign = campaigns.get(performance.campaign_id)
        if campaign is None:
            continue
        start_day = campaign.starts_at.date() if campaign.starts_at else None
        end_day = campaign.ends_at.date() if campaign.ends_at else None
        budget = performance.planned_budget_amount
        currency = performance.planned_budget_currency
        actual = performance.budget_consumption.measured_spend_in_budget_currency
        other_currency_spend = dict(performance.budget_consumption.spend_in_other_currencies)
        scheduled_days_elapsed: int | None = None
        scheduled_days_total: int | None = None
        expected: Decimal | None = None
        variance: Decimal | None = None
        variance_percent: float | None = None

        if budget is None or currency is None or budget <= 0:
            pacing_status = "no_budget"
        elif start_day is None or end_day is None:
            pacing_status = "schedule_incomplete"
        else:
            scheduled_days_total = (end_day - start_day).days + 1
            if as_of < start_day:
                scheduled_days_elapsed = 0
                expected = Decimal("0")
                pacing_status = "not_started"
            else:
                active_window_start = max(period_start, start_day)
                active_window_end = min(as_of, end_day)
                scheduled_days_elapsed = max(
                    0, (active_window_end - active_window_start).days + 1
                )
                expected = (
                    budget * Decimal(scheduled_days_elapsed)
                    / Decimal(scheduled_days_total)
                )
                if actual is None:
                    pacing_status = "no_spend_data"
                else:
                    variance = actual - expected
                    variance_percent = (
                        round(float(variance / expected * Decimal("100")), 4)
                        if expected > 0 else None
                    )
                    if actual > expected:
                        pacing_status = "ahead_of_pace"
                    elif actual < expected:
                        pacing_status = "behind_pace"
                    else:
                        pacing_status = "on_pace"
        pacing_counts[pacing_status] += 1
        items.append(CampaignBudgetPacingItem(
            campaign_id=performance.campaign_id,
            campaign_name=performance.name,
            campaign_status=performance.status,
            period_start=period_start,
            as_of=as_of,
            planned_budget_amount=budget,
            budget_currency=currency,
            actual_spend_in_budget_currency=actual,
            expected_spend_to_date=expected,
            variance_from_expected=variance,
            variance_percent=variance_percent,
            spend_in_other_currencies=other_currency_spend,
            scheduled_days_elapsed=scheduled_days_elapsed,
            scheduled_days_total=scheduled_days_total,
            pacing_status=pacing_status,
        ))

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.campaign_budget_pacing.read",
        target_type="crm_marketing_campaign_budget_pacing",
        target_key=f"{period_start.isoformat()}:{as_of.isoformat()}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "campaign_count": len(items),
            "truncated": portfolio.truncated,
            "pacing_status_counts": pacing_counts,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignBudgetPacingRead(
        period_start=period_start,
        as_of=as_of,
        campaign_count=len(items),
        items=items,
        truncated=portfolio.truncated,
        pacing_basis=(
            "Expected spend assumes planned budget is distributed linearly across the "
            "campaign's inclusive scheduled dates. Actual spend is measured only in the "
            "requested period and remains separated by currency; missing observations "
            "are not treated as zero."
        ),
    )




class CampaignBudgetPacingAlertsRead(BaseModel):
    period_start: date
    as_of: date
    variance_threshold_percent: float
    alert_count: int
    items: list[CampaignBudgetPacingItem]
    truncated: bool
    alert_basis: str


@router.get(
    "/campaigns/budget-pacing/alerts",
    response_model=CampaignBudgetPacingAlertsRead,
    operation_id="getMarketingManagerCampaignBudgetPacingAlerts",
    summary="List campaigns whose budget pace exceeds a manager-set variance threshold",
)
async def get_marketing_manager_campaign_budget_pacing_alerts(
    period_start: date = Query(...),
    as_of: date = Query(...),
    variance_threshold_percent: float = Query(10, ge=0, le=100),
    limit: int = Query(100, ge=1, le=500),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignBudgetPacingAlertsRead:
    report = await get_marketing_manager_campaign_budget_pacing(
        period_start=period_start,
        as_of=as_of,
        context=context,
    )
    matching = [
        item
        for item in report.items
        if item.pacing_status in {"ahead_of_pace", "behind_pace"}
        and item.variance_percent is not None
        and abs(item.variance_percent) >= variance_threshold_percent
    ]
    items = matching[:limit]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.campaign_budget_pacing.alerts.read",
        target_type="crm_marketing_campaign_budget_pacing_alerts",
        target_key=f"{period_start.isoformat()}:{as_of.isoformat()}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "variance_threshold_percent": variance_threshold_percent,
            "alert_count": len(items),
            "matching_count": len(matching),
            "truncated": len(matching) > len(items),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignBudgetPacingAlertsRead(
        period_start=period_start,
        as_of=as_of,
        variance_threshold_percent=variance_threshold_percent,
        alert_count=len(items),
        items=items,
        truncated=len(matching) > len(items),
        alert_basis=(
            "Includes only campaigns with observed same-currency spend and a pacing "
            "variance whose absolute percentage meets the requested threshold. "
            "Thresholds are relative to expected spend; missing or zero expected "
            "spend does not produce a percentage alert."
        ),
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
    generated_at: datetime
    report_definition_version: str
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
        generated_at=datetime.now(timezone.utc),
        report_definition_version="1",
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


def _csv_safe_text(value: str) -> str:
    """Neutralize spreadsheet formulas in untrusted text cells."""
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.get(
    "/campaigns/export.csv",
    response_class=Response,
    operation_id="exportMarketingManagerCampaignDashboardCsv",
    summary="Export the marketing manager campaign dashboard as CSV",
)
async def export_marketing_manager_campaign_dashboard_csv(
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    dashboard = await get_marketing_manager_campaign_dashboard(
        period_start=period_start,
        period_end=period_end,
        context=context,
    )
    columns = (
        "record_type", "key", "label", "currency", "metric", "value",
        "target", "actual", "status", "observed_days", "expected_days",
        "coverage_percent",
    )
    rows: list[dict[str, object]] = []

    def add_row(record_type: str, **values: object) -> None:
        rows.append({"record_type": record_type, **values})

    add_row("metadata", key="report_definition_version", value=dashboard.report_definition_version)
    add_row("metadata", key="generated_at", value=dashboard.generated_at.isoformat())
    add_row("metadata", key="period_start", value=dashboard.period_start.isoformat())
    add_row("metadata", key="period_end", value=dashboard.period_end.isoformat())
    add_row("metadata", key="dashboard_basis", value=dashboard.dashboard_basis)

    summary = dashboard.performance
    add_row("summary", key="campaign_count", value=summary.campaign_count)
    add_row("summary", key="measured_campaign_count", value=summary.measured_campaign_count)
    add_row("summary", key="campaigns_truncated", value=summary.truncated)
    for metric, value in summary.totals.items():
        add_row("summary_metric", metric=metric, value=value)
    for currency, value in summary.planned_budget_by_currency.items():
        add_row("planned_budget", currency=currency, value=value)
    for currency, value in summary.actual_spend_by_currency.items():
        add_row("actual_spend", currency=currency, value=value)
    for currency, value in summary.attributed_revenue_by_currency.items():
        add_row("attributed_revenue", currency=currency, value=value)
    for currency, value in summary.efficiency.attributed_revenue_minus_spend_by_currency.items():
        add_row("revenue_minus_spend", currency=currency, value=value)
    for currency, value in summary.efficiency.return_on_ad_spend_by_currency.items():
        add_row("return_on_ad_spend", currency=currency, value=value)

    def write_group(record_type: str, key: str, label: str, campaign_count: int,
                    totals: dict[str, int | None], spend: dict[str, Decimal],
                    revenue: dict[str, Decimal], efficiency: CampaignEfficiencyMetrics) -> None:
        add_row(record_type, key=key, label=label, metric="campaign_count", value=campaign_count)
        for metric, value in totals.items():
            add_row(record_type + "_metric", key=key, label=label, metric=metric, value=value)
        for currency, value in spend.items():
            add_row(record_type + "_spend", key=key, label=label, currency=currency, value=value)
        for currency, value in revenue.items():
            add_row(record_type + "_revenue", key=key, label=label, currency=currency, value=value)
        for currency, value in efficiency.attributed_revenue_minus_spend_by_currency.items():
            add_row(record_type + "_revenue_minus_spend", key=key, label=label, currency=currency, value=value)
        for currency, value in efficiency.return_on_ad_spend_by_currency.items():
            add_row(record_type + "_return_on_ad_spend", key=key, label=label, currency=currency, value=value)

    for item in dashboard.channel_performance:
        write_group(
            "channel", item.channel, item.channel, item.campaign_count, item.totals,
            item.actual_spend_by_currency, item.attributed_revenue_by_currency, item.efficiency,
        )
    for item in dashboard.segment_performance:
        write_group(
            "segment", str(item.segment_id), item.segment_name or "", item.campaign_count,
            item.totals, item.actual_spend_by_currency, item.attributed_revenue_by_currency,
            item.efficiency,
        )

    quality = dashboard.data_quality
    for key in (
        "campaigns_without_measurements", "expected_campaign_days",
        "covered_campaign_days", "missing_campaign_days",
        "out_of_schedule_measurement_days",
    ):
        add_row("data_quality", key=key, value=getattr(quality, key))
    for metric, coverage in quality.metric_coverage.items():
        add_row(
            "metric_coverage", metric=metric, observed_days=coverage.observed_days,
            expected_days=coverage.expected_days, value=coverage.missing_days,
            coverage_percent=coverage.coverage_percent,
        )

    targets = dashboard.target_attainment
    for metric, outcomes in targets.metric_outcomes.items():
        for status_key in ("met", "not_met", "no_data"):
            add_row(
                "target_outcome", key=metric, metric=status_key,
                value=getattr(outcomes, status_key),
            )
    for metric, variance in targets.metric_variances.items():
        for field in (
            "targeted_campaign_count", "complete_campaign_count", "incomplete_campaign_count",
            "target_total", "complete_actual_total", "complete_campaign_target_total",
            "complete_variance", "incomplete_target_total", "partial_actual_total",
        ):
            add_row("target_variance", key=metric, metric=field, value=getattr(variance, field))
    for signal in targets.manager_signals:
        add_row(
            "manager_signal", key=str(signal.campaign_id), label=signal.recommended_action,
            metric=signal.metric_key, target=signal.target, actual=signal.actual,
            currency=signal.currency, status=signal.signal_type,
            observed_days=signal.observed_days, expected_days=signal.period_days,
        )
    for outcome in targets.commerce_outcomes_by_currency:
        add_row(
            "commerce_outcome", currency=outcome.currency, metric="net_paid_amount",
            value=outcome.net_paid_amount,
        )
    for outcome in targets.commerce_outcomes_by_source_product:
        add_row(
            "commerce_source_outcome", key=outcome.source_product,
            currency=outcome.currency, metric="net_paid_amount", value=outcome.net_paid_amount,
        )

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        for field in ("record_type", "key", "label", "currency", "metric", "status"):
            value = row.get(field)
            if isinstance(value, str):
                row[field] = _csv_safe_text(value)
        writer.writerow(row)

    generated_at = dashboard.generated_at.isoformat()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.campaign_dashboard.exported",
        target_type="crm_marketing_manager_campaign_dashboard_export",
        target_key=f"{period_start.isoformat()}:{period_end.isoformat()}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "format": "csv",
            "report_definition_version": dashboard.report_definition_version,
            "generated_at": generated_at,
            "row_count": len(rows),
            "column_count": len(columns),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    filename = f"funnel-crm-campaign-dashboard-{period_start.isoformat()}-{period_end.isoformat()}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _canonical_dashboard_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@router.post(
    "/campaigns/snapshots",
    status_code=201,
    operation_id="createMarketingManagerCampaignDashboardSnapshot",
    summary="Create an immutable, hash-verified dashboard snapshot",
)
async def create_marketing_manager_dashboard_snapshot(
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    dashboard = await get_marketing_manager_campaign_dashboard(
        period_start=period_start, period_end=period_end, context=context
    )
    payload = dashboard.model_dump(mode="json")
    canonical = _canonical_dashboard_json(payload)
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result = await context.session.execute(
        text("""
            INSERT INTO crm_marketing_dashboard_snapshots
                (tenant_id, creator_identity_id, period_start, period_end,
                 report_definition_version, snapshot_hash, payload)
            VALUES
                (:tenant_id, :creator_identity_id, :period_start, :period_end,
                 :version, :snapshot_hash, CAST(:payload AS jsonb))
            RETURNING id, created_at
        """),
        {
            "tenant_id": context.access.tenant_id,
            "creator_identity_id": context.access.identity_id,
            "period_start": period_start,
            "period_end": period_end,
            "version": dashboard.report_definition_version,
            "snapshot_hash": snapshot_hash,
            "payload": canonical,
        },
    )
    row = result.mappings().one()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_snapshot.created",
        target_type="crm_marketing_dashboard_snapshot",
        target_key=str(row["id"]),
        organization_unit_id=None,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "report_definition_version": dashboard.report_definition_version,
            "snapshot_hash": snapshot_hash,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "report_definition_version": dashboard.report_definition_version,
        "snapshot_hash": snapshot_hash,
    }


@router.get(
    "/campaigns/snapshots",
    operation_id="listMarketingManagerCampaignDashboardSnapshots",
    summary="List the current user's dashboard snapshots",
)
async def list_marketing_manager_dashboard_snapshots(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    result = await context.session.execute(
        text("""
            SELECT id, period_start, period_end, report_definition_version,
                   snapshot_hash, created_at
            FROM crm_marketing_dashboard_snapshots
            WHERE tenant_id = :tenant_id AND creator_identity_id = :creator_identity_id
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "tenant_id": context.access.tenant_id,
            "creator_identity_id": context.access.identity_id,
            "limit": limit,
            "offset": offset,
        },
    )
    items = [
        {
            "id": str(row["id"]),
            "period_start": row["period_start"].isoformat(),
            "period_end": row["period_end"].isoformat(),
            "report_definition_version": row["report_definition_version"],
            "snapshot_hash": row["snapshot_hash"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in result.mappings()
    ]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_snapshot.listed",
        target_type="crm_marketing_dashboard_snapshot_collection",
        target_key=f"{offset}:{limit}",
        organization_unit_id=None,
        before_state=None,
        after_state={"returned_count": len(items), "offset": offset, "limit": limit},
        correlation_id=None,
    ))
    await context.session.flush()
    return {"items": items, "limit": limit, "offset": offset}


@router.get(
    "/campaigns/snapshots/{snapshot_id}",
    operation_id="getMarketingManagerCampaignDashboardSnapshot",
    summary="Retrieve and verify one of the current user's dashboard snapshots",
)
async def get_marketing_manager_dashboard_snapshot(
    snapshot_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    result = await context.session.execute(
        text("""
            SELECT id, period_start, period_end, report_definition_version,
                   snapshot_hash, payload, created_at
            FROM crm_marketing_dashboard_snapshots
            WHERE id = :id AND tenant_id = :tenant_id
              AND creator_identity_id = :creator_identity_id
        """),
        {
            "id": snapshot_id,
            "tenant_id": context.access.tenant_id,
            "creator_identity_id": context.access.identity_id,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard snapshot not found")
    payload = row["payload"]
    actual_hash = hashlib.sha256(
        _canonical_dashboard_json(payload).encode("utf-8")
    ).hexdigest()
    if actual_hash != row["snapshot_hash"]:
        raise HTTPException(status_code=500, detail="Dashboard snapshot integrity check failed")
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_snapshot.read",
        target_type="crm_marketing_dashboard_snapshot",
        target_key=str(snapshot_id),
        organization_unit_id=None,
        before_state=None,
        after_state={"snapshot_hash": actual_hash, "integrity_verified": True},
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat(),
        "period_start": row["period_start"].isoformat(),
        "period_end": row["period_end"].isoformat(),
        "report_definition_version": row["report_definition_version"],
        "snapshot_hash": actual_hash,
        "integrity_verified": True,
        "dashboard": payload,
    }


def _dashboard_numeric_values(value: object, path: str = "") -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"generated_at", "period_start", "period_end", "report_definition_version"}:
                continue
            values.update(_dashboard_numeric_values(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            identity = None
            if isinstance(item, dict):
                for key in ("channel", "segment_id", "campaign_id", "currency", "metric_key"):
                    if item.get(key) is not None:
                        identity = f"{key}={item[key]}"
                        break
            item_path = f"{path}[{identity or index}]"
            values.update(_dashboard_numeric_values(item, item_path))
    elif isinstance(value, bool) or value is None:
        return values
    elif isinstance(value, (int, float, Decimal)):
        values[path] = Decimal(str(value))
    elif isinstance(value, str) and "." in value:
        try:
            values[path] = Decimal(value)
        except Exception:
            pass
    return values


def _dashboard_snapshot_changes(
    baseline: dict[str, object], current: dict[str, object]
) -> list[dict[str, object]]:
    before = _dashboard_numeric_values(baseline)
    after = _dashboard_numeric_values(current)
    changes: list[dict[str, object]] = []
    for path in sorted(before.keys() | after.keys()):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if old is None:
            changes.append({"path": path, "status": "added", "previous": None,
                            "current": format(new, "f"), "absolute_change": None,
                            "percent_change": None})
        elif new is None:
            changes.append({"path": path, "status": "removed", "previous": format(old, "f"),
                            "current": None, "absolute_change": None, "percent_change": None})
        else:
            delta = new - old
            changes.append({
                "path": path,
                "status": "changed",
                "previous": format(old, "f"),
                "current": format(new, "f"),
                "absolute_change": format(delta, "f"),
                "percent_change": format((delta / old * Decimal("100")), "f") if old else None,
            })
    return changes


@router.get(
    "/campaigns/snapshot-comparisons",
    operation_id="compareMarketingManagerCampaignDashboardSnapshots",
    summary="Compare two verified dashboard snapshots for the same period and report version",
)
async def compare_marketing_manager_dashboard_snapshots(
    baseline_id: UUID = Query(...),
    current_id: UUID = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    if baseline_id == current_id:
        raise HTTPException(status_code=422, detail="Choose two different dashboard snapshots")
    result = await context.session.execute(
        text("""
            SELECT id, period_start, period_end, report_definition_version,
                   snapshot_hash, payload, created_at
            FROM crm_marketing_dashboard_snapshots
            WHERE id IN (:baseline_id, :current_id)
              AND tenant_id = :tenant_id
              AND creator_identity_id = :creator_identity_id
        """),
        {
            "baseline_id": baseline_id,
            "current_id": current_id,
            "tenant_id": context.access.tenant_id,
            "creator_identity_id": context.access.identity_id,
        },
    )
    rows = {row["id"]: row for row in result.mappings()}
    baseline = rows.get(baseline_id)
    current = rows.get(current_id)
    if baseline is None or current is None:
        raise HTTPException(status_code=404, detail="Dashboard snapshot not found")
    for row in (baseline, current):
        actual_hash = hashlib.sha256(
            _canonical_dashboard_json(row["payload"]).encode("utf-8")
        ).hexdigest()
        if actual_hash != row["snapshot_hash"]:
            raise HTTPException(status_code=500, detail="Dashboard snapshot integrity check failed")
    if (
        baseline["period_start"] != current["period_start"]
        or baseline["period_end"] != current["period_end"]
        or baseline["report_definition_version"] != current["report_definition_version"]
    ):
        raise HTTPException(
            status_code=422,
            detail="Snapshots must use the same reporting period and report definition version",
        )
    changes = _dashboard_snapshot_changes(baseline["payload"], current["payload"])
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_snapshot.compared",
        target_type="crm_marketing_dashboard_snapshot",
        target_key=f"{baseline_id}:{current_id}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "baseline_hash": baseline["snapshot_hash"],
            "current_hash": current["snapshot_hash"],
            "change_count": len(changes),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "baseline": {
            "id": str(baseline_id),
            "created_at": baseline["created_at"].isoformat(),
            "snapshot_hash": baseline["snapshot_hash"],
        },
        "current": {
            "id": str(current_id),
            "created_at": current["created_at"].isoformat(),
            "snapshot_hash": current["snapshot_hash"],
        },
        "period_start": baseline["period_start"].isoformat(),
        "period_end": baseline["period_end"].isoformat(),
        "report_definition_version": baseline["report_definition_version"],
        "change_count": len(changes),
        "changes": changes,
    }



@router.get(
    "/campaigns/snapshot-comparisons/export.csv",
    response_class=Response,
    operation_id="exportMarketingManagerCampaignDashboardSnapshotComparisonCsv",
    summary="Export a verified dashboard snapshot comparison as CSV",
)
async def export_marketing_manager_dashboard_snapshot_comparison_csv(
    baseline_id: UUID = Query(...),
    current_id: UUID = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    comparison = await compare_marketing_manager_dashboard_snapshots(
        baseline_id=baseline_id,
        current_id=current_id,
        context=context,
    )
    columns = (
        "record_type", "path", "status", "previous", "current",
        "absolute_change", "percent_change",
    )
    export_time = datetime.now(timezone.utc)
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    metadata = (
        ("baseline_id", comparison["baseline"]["id"]),
        ("current_id", comparison["current"]["id"]),
        ("baseline_hash", comparison["baseline"]["snapshot_hash"]),
        ("current_hash", comparison["current"]["snapshot_hash"]),
        ("period_start", comparison["period_start"]),
        ("period_end", comparison["period_end"]),
        ("report_definition_version", comparison["report_definition_version"]),
        ("generated_at", export_time.isoformat()),
        ("change_count", comparison["change_count"]),
    )
    for key, value in metadata:
        writer.writerow({"record_type": "metadata", "path": key, "current": value})
    for change in comparison["changes"]:
        writer.writerow({
            "record_type": "metric_change",
            "path": _csv_safe_text(str(change["path"])),
            "status": _csv_safe_text(str(change["status"])),
            "previous": change["previous"],
            "current": change["current"],
            "absolute_change": change["absolute_change"],
            "percent_change": change["percent_change"],
        })

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_snapshot_comparison.exported",
        target_type="crm_marketing_dashboard_snapshot_comparison",
        target_key=f"{baseline_id}:{current_id}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "format": "csv",
            "generated_at": export_time.isoformat(),
            "row_count": comparison["change_count"] + len(metadata),
            "column_count": len(columns),
            "baseline_hash": comparison["baseline"]["snapshot_hash"],
            "current_hash": comparison["current"]["snapshot_hash"],
        },
        correlation_id=None,
    ))
    await context.session.flush()
    filename = (
        "funnel-crm-campaign-snapshot-comparison-"
        f"{comparison['period_start']}-{comparison['period_end']}.csv"
    )
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class DashboardSnapshotActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    decision_note: str = Field(min_length=1, max_length=4000)
    due_on: date | None = None
    assigned_membership_id: UUID | None = None

    @field_validator("title", "decision_note")
    @classmethod
    def normalize_action_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must contain a non-whitespace character")
        return cleaned


class DashboardSnapshotActionClose(BaseModel):
    status: str = Field(pattern="^(completed|cancelled)$")
    outcome: str = Field(min_length=1, max_length=4000)

    @field_validator("outcome")
    @classmethod
    def normalize_outcome(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("outcome must contain a non-whitespace character")
        return cleaned


@router.post(
    "/campaigns/snapshots/{snapshot_id}/actions",
    status_code=201,
    operation_id="createMarketingManagerDashboardSnapshotAction",
    summary="Record a manager decision and follow-up action for a dashboard snapshot",
)
async def create_marketing_manager_dashboard_snapshot_action(
    snapshot_id: UUID,
    payload: DashboardSnapshotActionCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    snapshot = await context.session.execute(
        text("""
            SELECT id FROM crm_marketing_dashboard_snapshots
            WHERE id = :snapshot_id AND tenant_id = :tenant_id
              AND creator_identity_id = :identity_id
        """),
        {
            "snapshot_id": snapshot_id,
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    if snapshot.first() is None:
        raise HTTPException(status_code=404, detail="Dashboard snapshot not found")
    if payload.assigned_membership_id is not None:
        assignee = await context.session.execute(
            text("""
                SELECT id FROM workspace_memberships
                WHERE tenant_id = :tenant_id AND id = :membership_id
                  AND status = 'active'
            """),
            {
                "tenant_id": context.access.tenant_id,
                "membership_id": payload.assigned_membership_id,
            },
        )
        if assignee.first() is None:
            raise HTTPException(status_code=422, detail="Assignee is not an active workspace member")
    result = await context.session.execute(
        text("""
            INSERT INTO crm_marketing_dashboard_actions
                (tenant_id, snapshot_id, creator_identity_id, assigned_membership_id,
                 title, decision_note, due_on)
            VALUES
                (:tenant_id, :snapshot_id, :identity_id, :assigned_membership_id,
                 :title, :decision_note, :due_on)
            RETURNING id, status, created_at, updated_at
        """),
        {
            "tenant_id": context.access.tenant_id,
            "snapshot_id": snapshot_id,
            "identity_id": context.access.identity_id,
            "assigned_membership_id": payload.assigned_membership_id,
            "title": payload.title,
            "decision_note": payload.decision_note,
            "due_on": payload.due_on,
        },
    )
    row = result.mappings().one()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.created",
        target_type="crm_marketing_dashboard_action",
        target_key=str(row["id"]),
        organization_unit_id=None,
        before_state=None,
        after_state={
            "snapshot_id": str(snapshot_id),
            "status": row["status"],
            "due_on": payload.due_on.isoformat() if payload.due_on else None,
            "assigned_membership_id": (
                str(payload.assigned_membership_id)
                if payload.assigned_membership_id else None
            ),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "id": str(row["id"]),
        "snapshot_id": str(snapshot_id),
        "title": payload.title,
        "decision_note": payload.decision_note,
        "assigned_membership_id": (
            str(payload.assigned_membership_id) if payload.assigned_membership_id else None
        ),
        "due_on": payload.due_on.isoformat() if payload.due_on else None,
        "status": row["status"],
        "outcome": None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


@router.get(
    "/campaigns/snapshots/{snapshot_id}/actions",
    operation_id="listMarketingManagerDashboardSnapshotActions",
    summary="List follow-up actions for a dashboard snapshot",
)
async def list_marketing_manager_dashboard_snapshot_actions(
    snapshot_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    result = await context.session.execute(
        text("""
            SELECT id, title, decision_note, assigned_membership_id, due_on,
                   status, outcome, created_at, updated_at
            FROM crm_marketing_dashboard_actions
            WHERE snapshot_id = :snapshot_id AND tenant_id = :tenant_id
              AND creator_identity_id = :identity_id
            ORDER BY created_at, id
        """),
        {
            "snapshot_id": snapshot_id,
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    rows = result.mappings().all()
    items = [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "decision_note": row["decision_note"],
            "assigned_membership_id": (
                str(row["assigned_membership_id"])
                if row["assigned_membership_id"] else None
            ),
            "due_on": row["due_on"].isoformat() if row["due_on"] else None,
            "status": row["status"],
            "outcome": row["outcome"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.listed",
        target_type="crm_marketing_dashboard_snapshot",
        target_key=str(snapshot_id),
        organization_unit_id=None,
        before_state=None,
        after_state={"returned_count": len(items)},
        correlation_id=None,
    ))
    await context.session.flush()
    return {"items": items}


@router.patch(
    "/campaigns/snapshot-actions/{action_id}",
    operation_id="closeMarketingManagerDashboardSnapshotAction",
    summary="Complete or cancel an open dashboard follow-up action",
)
async def close_marketing_manager_dashboard_snapshot_action(
    action_id: UUID,
    payload: DashboardSnapshotActionClose,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    result = await context.session.execute(
        text("""
            UPDATE crm_marketing_dashboard_actions
            SET status = :status, outcome = :outcome, updated_at = now()
            WHERE id = :action_id AND tenant_id = :tenant_id
              AND (creator_identity_id = :identity_id
                   OR assigned_membership_id = :membership_id)
              AND status = 'open'
            RETURNING id, snapshot_id, status, outcome, updated_at
        """),
        {
            "action_id": action_id,
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
            "membership_id": context.access.membership_id,
            "status": payload.status,
            "outcome": payload.outcome,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        existing = await context.session.execute(
            text("""
                SELECT status FROM crm_marketing_dashboard_actions
                WHERE id = :action_id AND tenant_id = :tenant_id
                  AND (creator_identity_id = :identity_id
                       OR assigned_membership_id = :membership_id)
            """),
            {
                "action_id": action_id,
                "tenant_id": context.access.tenant_id,
                "identity_id": context.access.identity_id,
                "membership_id": context.access.membership_id,
            },
        )
        if existing.first() is None:
            raise HTTPException(status_code=404, detail="Dashboard action not found")
        raise HTTPException(status_code=409, detail="Dashboard action is already closed")
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.closed",
        target_type="crm_marketing_dashboard_action",
        target_key=str(action_id),
        organization_unit_id=None,
        before_state={"status": "open"},
        after_state={
            "status": row["status"],
            "outcome": payload.outcome,
            "snapshot_id": str(row["snapshot_id"]),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "id": str(row["id"]),
        "snapshot_id": str(row["snapshot_id"]),
        "status": row["status"],
        "outcome": row["outcome"],
        "updated_at": row["updated_at"].isoformat(),
    }


@router.get(
    "/campaigns/snapshot-actions",
    operation_id="listMarketingManagerDashboardActionWorklist",
    summary="List open and closed actions created by or assigned to the current member",
)
async def list_marketing_manager_dashboard_action_worklist(
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(open|completed|cancelled)$"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    result = await context.session.execute(
        text("""
            SELECT id, snapshot_id, title, decision_note, assigned_membership_id,
                   due_on, status, outcome, created_at, updated_at
            FROM crm_marketing_dashboard_actions
            WHERE tenant_id = :tenant_id
              AND (creator_identity_id = :identity_id
                   OR assigned_membership_id = :membership_id)
              AND (CAST(:status_filter AS VARCHAR) IS NULL OR status = :status_filter)
            ORDER BY
                CASE WHEN status = 'open' THEN 0 ELSE 1 END,
                due_on ASC NULLS LAST, created_at DESC, id
            LIMIT :limit OFFSET :offset
        """),
        {
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
            "membership_id": context.access.membership_id,
            "status_filter": status_filter,
            "limit": limit,
            "offset": offset,
        },
    )
    rows = result.mappings().all()
    items = [
        {
            "id": str(row["id"]),
            "snapshot_id": str(row["snapshot_id"]),
            "title": row["title"],
            "decision_note": row["decision_note"],
            "assigned_membership_id": (
                str(row["assigned_membership_id"])
                if row["assigned_membership_id"] else None
            ),
            "due_on": row["due_on"].isoformat() if row["due_on"] else None,
            "status": row["status"],
            "outcome": row["outcome"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.worklist_read",
        target_type="crm_marketing_dashboard_action_collection",
        target_key=f"{status_filter or 'all'}:{offset}:{limit}",
        organization_unit_id=None,
        before_state=None,
        after_state={"returned_count": len(items)},
        correlation_id=None,
    ))
    await context.session.flush()
    return {"items": items, "status": status_filter, "limit": limit, "offset": offset}



@router.get(
    "/campaigns/snapshot-actions/analytics",
    operation_id="getMarketingManagerDashboardActionAnalytics",
    summary="Review completion, overdue, and closure-time metrics for dashboard actions",
)
async def get_marketing_manager_dashboard_action_analytics(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    result = await context.session.execute(
        text("""
            SELECT
                CURRENT_DATE AS as_of,
                COUNT(*) AS total_count,
                COUNT(*) FILTER (WHERE status = 'open') AS open_count,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                COUNT(*) FILTER (
                    WHERE status = 'open' AND due_on < CURRENT_DATE
                ) AS overdue_open_count,
                COUNT(*) FILTER (
                    WHERE status = 'open'
                      AND due_on >= CURRENT_DATE
                      AND due_on <= CURRENT_DATE + 7
                ) AS due_next_7_days_open_count,
                ROUND(
                    COUNT(*) FILTER (WHERE status = 'completed')::numeric * 100
                    / NULLIF(COUNT(*) FILTER (
                        WHERE status IN ('completed', 'cancelled')
                    ), 0),
                    2
                ) AS completion_rate_percent,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 86400)
                    FILTER (WHERE status IN ('completed', 'cancelled'))::numeric,
                    2
                ) AS average_days_to_close
            FROM crm_marketing_dashboard_actions
            WHERE tenant_id = :tenant_id
              AND (creator_identity_id = :identity_id
                   OR assigned_membership_id = :membership_id)
        """),
        {
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
            "membership_id": context.access.membership_id,
        },
    )
    row = result.mappings().one()
    metrics = {
        "as_of": row["as_of"].isoformat(),
        "total_count": row["total_count"],
        "open_count": row["open_count"],
        "completed_count": row["completed_count"],
        "cancelled_count": row["cancelled_count"],
        "overdue_open_count": row["overdue_open_count"],
        "due_next_7_days_open_count": row["due_next_7_days_open_count"],
        "completion_rate_percent": (
            format(row["completion_rate_percent"], "f")
            if row["completion_rate_percent"] is not None else None
        ),
        "average_days_to_close": (
            format(row["average_days_to_close"], "f")
            if row["average_days_to_close"] is not None else None
        ),
    }
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.analytics_read",
        target_type="crm_marketing_dashboard_action_analytics",
        target_key=metrics["as_of"],
        organization_unit_id=None,
        before_state=None,
        after_state={
            "total_count": metrics["total_count"],
            "open_count": metrics["open_count"],
            "completed_count": metrics["completed_count"],
            "overdue_open_count": metrics["overdue_open_count"],
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return metrics


class DashboardActionVerificationCreate(BaseModel):
    current_snapshot_id: UUID
    metric_path: str = Field(min_length=1, max_length=500)
    expected_direction: str | None = Field(
        default=None, pattern="^(increase|decrease|unchanged)$"
    )

    @field_validator("metric_path")
    @classmethod
    def normalize_metric_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("metric_path must contain a non-whitespace character")
        return cleaned


@router.post(
    "/campaigns/snapshot-actions/{action_id}/verifications",
    status_code=201,
    operation_id="verifyMarketingManagerDashboardActionOutcome",
    summary="Record the observed metric movement after a manager action",
)
async def verify_marketing_manager_dashboard_action_outcome(
    action_id: UUID,
    payload: DashboardActionVerificationCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    action_result = await context.session.execute(
        text("""
            SELECT a.id, a.snapshot_id, a.creator_identity_id,
                   baseline.period_start, baseline.period_end,
                   baseline.report_definition_version, baseline.snapshot_hash,
                   baseline.payload, baseline.created_at
            FROM crm_marketing_dashboard_actions AS a
            JOIN crm_marketing_dashboard_snapshots AS baseline
              ON baseline.tenant_id = a.tenant_id AND baseline.id = a.snapshot_id
            WHERE a.id = :action_id AND a.tenant_id = :tenant_id
              AND a.creator_identity_id = :identity_id
        """),
        {
            "action_id": action_id,
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    action = action_result.mappings().one_or_none()
    if action is None:
        raise HTTPException(status_code=404, detail="Dashboard action not found")

    current_result = await context.session.execute(
        text("""
            SELECT id, period_start, period_end, report_definition_version,
                   snapshot_hash, payload, created_at
            FROM crm_marketing_dashboard_snapshots
            WHERE id = :snapshot_id AND tenant_id = :tenant_id
              AND creator_identity_id = :identity_id
        """),
        {
            "snapshot_id": payload.current_snapshot_id,
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    current = current_result.mappings().one_or_none()
    if current is None:
        raise HTTPException(status_code=404, detail="Dashboard snapshot not found")
    if (
        action["period_start"] != current["period_start"]
        or action["period_end"] != current["period_end"]
        or action["report_definition_version"] != current["report_definition_version"]
    ):
        raise HTTPException(
            status_code=422,
            detail="Snapshots must use the same reporting period and report definition version",
        )
    if current["created_at"] <= action["created_at"]:
        raise HTTPException(status_code=422, detail="Follow-up snapshot must be newer than the baseline")
    for snapshot_hash, snapshot_payload in (
        (action["snapshot_hash"], action["payload"]),
        (current["snapshot_hash"], current["payload"]),
    ):
        actual_hash = hashlib.sha256(
            _canonical_dashboard_json(snapshot_payload).encode("utf-8")
        ).hexdigest()
        if actual_hash != snapshot_hash:
            raise HTTPException(status_code=500, detail="Dashboard snapshot integrity check failed")

    baseline_metrics = _dashboard_numeric_values(action["payload"])
    current_metrics = _dashboard_numeric_values(current["payload"])
    if payload.metric_path not in baseline_metrics or payload.metric_path not in current_metrics:
        raise HTTPException(
            status_code=422,
            detail="Metric path must exist as a numeric value in both snapshots",
        )
    baseline_value = baseline_metrics[payload.metric_path]
    current_value = current_metrics[payload.metric_path]
    delta = current_value - baseline_value
    direction_matched: bool | None = None
    if payload.expected_direction is not None:
        direction_matched = {
            "increase": delta > 0,
            "decrease": delta < 0,
            "unchanged": delta == 0,
        }[payload.expected_direction]
    result = await context.session.execute(
        text("""
            INSERT INTO crm_marketing_dashboard_action_verifications
                (tenant_id, action_id, baseline_snapshot_id, current_snapshot_id,
                 metric_path, baseline_value, current_value, absolute_change,
                 expected_direction, direction_matched)
            VALUES
                (:tenant_id, :action_id, :baseline_snapshot_id, :current_snapshot_id,
                 :metric_path, :baseline_value, :current_value, :absolute_change,
                 :expected_direction, :direction_matched)
            ON CONFLICT (tenant_id, action_id, current_snapshot_id, metric_path)
            DO NOTHING
            RETURNING id, verified_at
        """),
        {
            "tenant_id": context.access.tenant_id,
            "action_id": action_id,
            "baseline_snapshot_id": action["snapshot_id"],
            "current_snapshot_id": current["id"],
            "metric_path": payload.metric_path,
            "baseline_value": baseline_value,
            "current_value": current_value,
            "absolute_change": delta,
            "expected_direction": payload.expected_direction,
            "direction_matched": direction_matched,
        },
    )
    verification = result.mappings().one_or_none()
    if verification is None:
        raise HTTPException(
            status_code=409,
            detail="This action and metric were already verified against that snapshot",
        )
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.outcome_verified",
        target_type="crm_marketing_dashboard_action_verification",
        target_key=str(verification["id"]),
        organization_unit_id=None,
        before_state=None,
        after_state={
            "action_id": str(action_id),
            "baseline_snapshot_id": str(action["snapshot_id"]),
            "current_snapshot_id": str(current["id"]),
            "baseline_hash": action["snapshot_hash"],
            "current_hash": current["snapshot_hash"],
            "metric_path": payload.metric_path,
            "expected_direction": payload.expected_direction,
            "direction_matched": direction_matched,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "id": str(verification["id"]),
        "action_id": str(action_id),
        "baseline_snapshot_id": str(action["snapshot_id"]),
        "current_snapshot_id": str(current["id"]),
        "metric_path": payload.metric_path,
        "baseline_value": format(baseline_value, "f"),
        "current_value": format(current_value, "f"),
        "absolute_change": format(delta, "f"),
        "expected_direction": payload.expected_direction,
        "direction_matched": direction_matched,
        "verified_at": verification["verified_at"].isoformat(),
        "interpretation": (
            "Observed metric movement only; this comparison does not establish that "
            "the action caused the change."
        ),
    }


@router.get(
    "/campaigns/snapshot-actions/{action_id}/verifications",
    operation_id="listMarketingManagerDashboardActionVerifications",
    summary="List recorded metric follow-up observations for a manager action",
)
async def list_marketing_manager_dashboard_action_verifications(
    action_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    action = await context.session.execute(
        text("""
            SELECT id FROM crm_marketing_dashboard_actions
            WHERE id = :action_id AND tenant_id = :tenant_id
              AND creator_identity_id = :identity_id
        """),
        {
            "action_id": action_id,
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    if action.first() is None:
        raise HTTPException(status_code=404, detail="Dashboard action not found")
    result = await context.session.execute(
        text("""
            SELECT id, baseline_snapshot_id, current_snapshot_id, metric_path,
                   baseline_value, current_value, absolute_change,
                   expected_direction, direction_matched, verified_at
            FROM crm_marketing_dashboard_action_verifications
            WHERE tenant_id = :tenant_id AND action_id = :action_id
            ORDER BY verified_at DESC, id DESC
        """),
        {"tenant_id": context.access.tenant_id, "action_id": action_id},
    )
    items = [
        {
            "id": str(row["id"]),
            "baseline_snapshot_id": str(row["baseline_snapshot_id"]),
            "current_snapshot_id": str(row["current_snapshot_id"]),
            "metric_path": row["metric_path"],
            "baseline_value": format(row["baseline_value"], "f"),
            "current_value": format(row["current_value"], "f"),
            "absolute_change": format(row["absolute_change"], "f"),
            "expected_direction": row["expected_direction"],
            "direction_matched": row["direction_matched"],
            "verified_at": row["verified_at"].isoformat(),
        }
        for row in result.mappings()
    ]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.verifications_read",
        target_type="crm_marketing_dashboard_action",
        target_key=str(action_id),
        organization_unit_id=None,
        before_state=None,
        after_state={"returned_count": len(items)},
        correlation_id=None,
    ))
    await context.session.flush()
    return {"items": items}



async def _read_marketing_manager_action_learning(
    context: TenantSessionContext,
) -> dict[str, object]:
    summary_result = await context.session.execute(
        text("""
            SELECT
                CURRENT_DATE AS as_of,
                COUNT(*) AS verification_count,
                COUNT(DISTINCT v.action_id) AS action_count,
                COUNT(*) FILTER (WHERE v.expected_direction IS NOT NULL) AS expected_count,
                COUNT(*) FILTER (WHERE v.direction_matched IS TRUE) AS matched_count,
                COUNT(*) FILTER (WHERE v.expected_direction = 'increase') AS expected_increase_count,
                COUNT(*) FILTER (WHERE v.expected_direction = 'decrease') AS expected_decrease_count,
                COUNT(*) FILTER (WHERE v.expected_direction = 'unchanged') AS expected_unchanged_count,
                COUNT(*) FILTER (
                    WHERE v.expected_direction IS NOT NULL AND v.direction_matched IS FALSE
                ) AS not_matched_count
            FROM crm_marketing_dashboard_action_verifications AS v
            JOIN crm_marketing_dashboard_actions AS a
              ON a.tenant_id = v.tenant_id AND a.id = v.action_id
            WHERE v.tenant_id = :tenant_id
              AND a.creator_identity_id = :identity_id
        """),
        {
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    summary_row = summary_result.mappings().one()
    grouped_result = await context.session.execute(
        text("""
            SELECT
                v.metric_path,
                COUNT(*) AS verification_count,
                COUNT(*) FILTER (WHERE v.expected_direction IS NOT NULL) AS expected_count,
                COUNT(*) FILTER (WHERE v.direction_matched IS TRUE) AS matched_count,
                COUNT(*) FILTER (
                    WHERE v.expected_direction IS NOT NULL AND v.direction_matched IS FALSE
                ) AS not_matched_count,
                COUNT(*) FILTER (WHERE v.absolute_change > 0) AS increase_count,
                COUNT(*) FILTER (WHERE v.absolute_change < 0) AS decrease_count,
                COUNT(*) FILTER (WHERE v.absolute_change = 0) AS unchanged_count,
                AVG(v.absolute_change) AS average_observed_change,
                ROUND(
                    COUNT(*) FILTER (WHERE v.direction_matched IS TRUE)::numeric * 100
                    / NULLIF(COUNT(*) FILTER (
                        WHERE v.expected_direction IS NOT NULL
                    ), 0),
                    2
                ) AS direction_match_rate_percent
            FROM crm_marketing_dashboard_action_verifications AS v
            JOIN crm_marketing_dashboard_actions AS a
              ON a.tenant_id = v.tenant_id AND a.id = v.action_id
            WHERE v.tenant_id = :tenant_id
              AND a.creator_identity_id = :identity_id
            GROUP BY v.metric_path
            ORDER BY v.metric_path
        """),
        {
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
        },
    )
    groups = [
        {
            "metric_path": row["metric_path"],
            "verification_count": row["verification_count"],
            "expected_count": row["expected_count"],
            "matched_count": row["matched_count"],
            "not_matched_count": row["not_matched_count"],
            "increase_count": row["increase_count"],
            "decrease_count": row["decrease_count"],
            "unchanged_count": row["unchanged_count"],
            "average_observed_change": (
                format(row["average_observed_change"], "f")
                if row["average_observed_change"] is not None else None
            ),
            "direction_match_rate_percent": (
                format(row["direction_match_rate_percent"], "f")
                if row["direction_match_rate_percent"] is not None else None
            ),
        }
        for row in grouped_result.mappings()
    ]
    expected_count = summary_row["expected_count"]
    summary = {
        "as_of": summary_row["as_of"].isoformat(),
        "verification_count": summary_row["verification_count"],
        "action_count": summary_row["action_count"],
        "expected_count": expected_count,
        "matched_count": summary_row["matched_count"],
        "not_matched_count": summary_row["not_matched_count"],
        "expected_increase_count": summary_row["expected_increase_count"],
        "expected_decrease_count": summary_row["expected_decrease_count"],
        "expected_unchanged_count": summary_row["expected_unchanged_count"],
        "direction_match_rate_percent": (
            format(
                (summary_row["matched_count"] * Decimal("100")) / expected_count,
                ".2f",
            )
            if expected_count else None
        ),
    }
    return {"summary": summary, "metrics": groups}


@router.get(
    "/campaigns/snapshot-actions/verification-analytics",
    operation_id="getMarketingManagerActionLearningAnalytics",
    summary="Aggregate observed action follow-up results by metric",
)
async def get_marketing_manager_action_learning_analytics(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    report = await _read_marketing_manager_action_learning(context)
    summary = report["summary"]
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.learning_analytics_read",
        target_type="crm_marketing_dashboard_action_learning_analytics",
        target_key=summary["as_of"],
        organization_unit_id=None,
        before_state=None,
        after_state={
            "verification_count": summary["verification_count"],
            "action_count": summary["action_count"],
            "metric_count": len(report["metrics"]),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return report


@router.get(
    "/campaigns/snapshot-actions/verification-analytics/export.csv",
    response_class=Response,
    operation_id="exportMarketingManagerActionLearningAnalyticsCsv",
    summary="Export action follow-up analytics as CSV",
)
async def export_marketing_manager_action_learning_analytics_csv(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    report = await _read_marketing_manager_action_learning(context)
    summary = report["summary"]
    columns = (
        "record_type", "metric_path", "value", "verification_count", "expected_count",
        "matched_count", "not_matched_count", "direction_match_rate_percent",
        "increase_count", "decrease_count", "unchanged_count",
        "average_observed_change",
    )
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for key in (
        "as_of", "verification_count", "action_count", "expected_count",
        "matched_count", "not_matched_count", "direction_match_rate_percent",
    ):
        writer.writerow({
            "record_type": "summary",
            "metric_path": key,
            "value": summary[key],
        })
    for metric in report["metrics"]:
        writer.writerow({
            "record_type": "metric",
            "metric_path": _csv_safe_text(str(metric["metric_path"])),
            "verification_count": metric["verification_count"],
            "expected_count": metric["expected_count"],
            "matched_count": metric["matched_count"],
            "not_matched_count": metric["not_matched_count"],
            "direction_match_rate_percent": metric["direction_match_rate_percent"],
            "increase_count": metric["increase_count"],
            "decrease_count": metric["decrease_count"],
            "unchanged_count": metric["unchanged_count"],
            "average_observed_change": metric["average_observed_change"],
        })

    export_time = datetime.now(timezone.utc)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.learning_analytics_exported",
        target_type="crm_marketing_dashboard_action_learning_analytics",
        target_key=summary["as_of"],
        organization_unit_id=None,
        before_state=None,
        after_state={
            "format": "csv",
            "generated_at": export_time.isoformat(),
            "row_count": len(report["metrics"]) + 7,
            "column_count": len(columns),
            "verification_count": summary["verification_count"],
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="funnel-crm-action-learning-analytics.csv"'
        },
    )



@router.get(
    "/campaigns/snapshot-actions/alerts",
    operation_id="getMarketingManagerDashboardActionDeadlineAlerts",
    summary="Review overdue and upcoming dashboard follow-up actions",
)
async def get_marketing_manager_dashboard_action_deadline_alerts(
    limit: int = Query(default=50, ge=1, le=100),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, object]:
    summary_result = await context.session.execute(
        text("""
            SELECT
                CURRENT_DATE AS as_of,
                COUNT(*) FILTER (WHERE due_on < CURRENT_DATE) AS overdue_count,
                COUNT(*) FILTER (WHERE due_on = CURRENT_DATE) AS due_today_count,
                COUNT(*) FILTER (
                    WHERE due_on > CURRENT_DATE AND due_on <= CURRENT_DATE + 7
                ) AS due_next_7_days_count
            FROM crm_marketing_dashboard_actions
            WHERE tenant_id = :tenant_id
              AND (creator_identity_id = :identity_id
                   OR assigned_membership_id = :membership_id)
              AND status = 'open'
              AND due_on IS NOT NULL
        """),
        {
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
            "membership_id": context.access.membership_id,
        },
    )
    summary = summary_result.mappings().one()
    result = await context.session.execute(
        text("""
            SELECT id, snapshot_id, title, assigned_membership_id, due_on,
                   CURRENT_DATE AS as_of
            FROM crm_marketing_dashboard_actions
            WHERE tenant_id = :tenant_id
              AND (creator_identity_id = :identity_id
                   OR assigned_membership_id = :membership_id)
              AND status = 'open'
              AND due_on IS NOT NULL
              AND due_on <= CURRENT_DATE + 7
            ORDER BY due_on, created_at, id
            LIMIT :limit
        """),
        {
            "tenant_id": context.access.tenant_id,
            "identity_id": context.access.identity_id,
            "membership_id": context.access.membership_id,
            "limit": limit,
        },
    )
    rows = result.mappings().all()
    items = []
    for row in rows:
        days_until_due = (row["due_on"] - row["as_of"]).days
        if days_until_due < 0:
            deadline_state = "overdue"
        elif days_until_due == 0:
            deadline_state = "due_today"
        else:
            deadline_state = "due_soon"
        items.append({
            "id": str(row["id"]),
            "snapshot_id": str(row["snapshot_id"]),
            "title": row["title"],
            "assigned_membership_id": (
                str(row["assigned_membership_id"])
                if row["assigned_membership_id"] else None
            ),
            "due_on": row["due_on"].isoformat(),
            "deadline_state": deadline_state,
            "days_until_due": days_until_due,
        })
    total_alerts = (
        summary["overdue_count"] + summary["due_today_count"]
        + summary["due_next_7_days_count"]
    )
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.dashboard_action.deadline_alerts_read",
        target_type="crm_marketing_dashboard_action_alerts",
        target_key=summary["as_of"].isoformat(),
        organization_unit_id=None,
        before_state=None,
        after_state={
            "overdue_count": summary["overdue_count"],
            "due_today_count": summary["due_today_count"],
            "due_next_7_days_count": summary["due_next_7_days_count"],
            "returned_count": len(items),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "as_of": summary["as_of"].isoformat(),
        "overdue_count": summary["overdue_count"],
        "due_today_count": summary["due_today_count"],
        "due_next_7_days_count": summary["due_next_7_days_count"],
        "items": items,
        "limit": limit,
        "truncated": total_alerts > len(items),
    }


@router.get(
    "/campaigns/budget-pacing/export.csv",
    response_class=Response,
    operation_id="exportMarketingManagerCampaignBudgetPacingCsv",
    summary="Export campaign budget pacing data as a currency-separated CSV",
)
async def export_marketing_manager_campaign_budget_pacing_csv(
    period_start: date = Query(...),
    as_of: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    report = await get_marketing_manager_campaign_budget_pacing(
        period_start=period_start,
        as_of=as_of,
        context=context,
    )
    columns = (
        "record_type", "campaign_id", "campaign_name", "currency", "pacing_status",
        "planned_budget", "actual_spend", "expected_spend", "variance",
        "variance_percent", "scheduled_days_elapsed", "scheduled_days_total",
        "other_currency_spend",
    )
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerow({
        "record_type": "metadata",
        "pacing_status": "report_period",
        "planned_budget": report.period_start.isoformat(),
        "actual_spend": report.as_of.isoformat(),
        "expected_spend": report.pacing_basis,
    })
    for item in report.items:
        writer.writerow({
            "record_type": "campaign",
            "campaign_id": str(item.campaign_id),
            "campaign_name": _csv_safe_text(item.campaign_name),
            "currency": item.budget_currency,
            "pacing_status": _csv_safe_text(item.pacing_status),
            "planned_budget": item.planned_budget_amount,
            "actual_spend": item.actual_spend_in_budget_currency,
            "expected_spend": item.expected_spend_to_date,
            "variance": item.variance_from_expected,
            "variance_percent": item.variance_percent,
            "scheduled_days_elapsed": item.scheduled_days_elapsed,
            "scheduled_days_total": item.scheduled_days_total,
            "other_currency_spend": json.dumps(
                {currency: str(amount) for currency, amount in item.spend_in_other_currencies.items()},
                sort_keys=True,
            ),
        })
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_manager.campaign_budget_pacing.exported",
        target_type="crm_marketing_campaign_budget_pacing",
        target_key=f"{period_start.isoformat()}:{as_of.isoformat()}",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "format": "csv",
            "row_count": len(report.items) + 1,
            "column_count": len(columns),
            "campaign_count": report.campaign_count,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    filename = f"funnel-crm-campaign-budget-pacing-{as_of.isoformat()}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
