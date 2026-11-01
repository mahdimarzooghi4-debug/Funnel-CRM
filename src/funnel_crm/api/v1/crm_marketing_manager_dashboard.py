"""Unified read-only dashboard for marketing managers."""

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from io import StringIO
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from pydantic import BaseModel

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
