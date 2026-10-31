"""Capture and aggregate observed daily campaign measurements."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaigns", tags=["CRM campaign measurement"])


class CampaignMeasurementUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_label: str = Field(min_length=1, max_length=120)
    impressions: int | None = Field(default=None, ge=0, le=9223372036854775807)
    reach: int | None = Field(default=None, ge=0, le=9223372036854775807)
    clicks: int | None = Field(default=None, ge=0, le=9223372036854775807)
    responses: int | None = Field(default=None, ge=0, le=9223372036854775807)
    leads: int | None = Field(default=None, ge=0, le=9223372036854775807)
    conversions: int | None = Field(default=None, ge=0, le=9223372036854775807)
    assigned_count: int | None = Field(default=None, ge=0, le=9223372036854775807)
    exposure_count: int | None = Field(default=None, ge=0, le=9223372036854775807)
    return_count: int | None = Field(default=None, ge=0, le=9223372036854775807)
    actual_spend_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    actual_spend_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    incentive_cost_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    incentive_cost_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    refunded_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    refunded_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    attributed_revenue_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    attributed_revenue_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("source_label")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("source_label must contain a non-whitespace character")
        return result

    @model_validator(mode="after")
    def validate_observation(self) -> "CampaignMeasurementUpsert":
        if (self.actual_spend_amount is None) != (self.actual_spend_currency is None):
            raise ValueError("actual spend amount and currency must be provided together")
        if (self.attributed_revenue_amount is None) != (self.attributed_revenue_currency is None):
            raise ValueError("attributed revenue amount and currency must be provided together")
        if (self.incentive_cost_amount is None) != (self.incentive_cost_currency is None):
            raise ValueError("incentive cost amount and currency must be provided together")
        if (self.refunded_amount is None) != (self.refunded_currency is None):
            raise ValueError("refunded amount and currency must be provided together")
        if all(getattr(self, key) is None for key in (
            "impressions", "reach", "clicks", "responses", "leads", "conversions",
            "assigned_count", "exposure_count",
            "return_count", "actual_spend_amount", "incentive_cost_amount",
            "refunded_amount", "attributed_revenue_amount",
        )):
            raise ValueError("at least one observed metric is required")
        return self


class CampaignMeasurementRead(BaseModel):
    id: UUID
    campaign_id: UUID
    organization_unit_id: UUID
    measured_on: date
    source_label: str
    impressions: int | None
    reach: int | None
    clicks: int | None
    responses: int | None
    leads: int | None
    conversions: int | None
    assigned_count: int | None
    exposure_count: int | None
    return_count: int | None
    actual_spend_amount: Decimal | None
    actual_spend_currency: str | None
    incentive_cost_amount: Decimal | None
    incentive_cost_currency: str | None
    refunded_amount: Decimal | None
    refunded_currency: str | None
    attributed_revenue_amount: Decimal | None
    attributed_revenue_currency: str | None


class CampaignMeasurementTotals(BaseModel):
    period_start: date
    period_end: date
    record_count: int
    source_labels: list[str]
    coverage_days: dict[str, int]
    totals: dict[str, int | None]
    click_through_rate_percent: float | None
    lead_rate_per_click_percent: float | None
    conversion_rate_per_click_percent: float | None
    actual_spend_by_currency: dict[str, Decimal]
    incentive_cost_by_currency: dict[str, Decimal]
    refunded_amount_by_currency: dict[str, Decimal]
    attributed_revenue_by_currency: dict[str, Decimal]


async def _require_permission(
    context: TenantSessionContext, *, permission_key: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Campaign measurement action is not authorized for this organization scope")


async def _load_campaign(
    context: TenantSessionContext, campaign_id: UUID
) -> CRMMarketingCampaign:
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _audit_measurement(
    context: TenantSessionContext,
    *,
    campaign: CRMMarketingCampaign,
    measurement: CRMMarketingCampaignMeasurement,
    action: str,
) -> None:
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key=f"crm_marketing_campaign_measurement.{action}",
            target_type="crm_marketing_campaign_measurement",
            target_key=str(measurement.id),
            organization_unit_id=campaign.organization_unit_id,
            before_state=None,
            after_state={
                "campaign_id": str(campaign.id),
                "measured_on": measurement.measured_on.isoformat(),
                "source_label": measurement.source_label,
            },
            correlation_id=None,
        )
    )


@router.put(
    "/{campaign_id}/measurements/{measured_on}",
    response_model=CampaignMeasurementRead,
    operation_id="upsertCRMMarketingCampaignMeasurement",
)
async def upsert_campaign_measurement(
    campaign_id: UUID,
    measured_on: date,
    payload: CampaignMeasurementUpsert,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignMeasurementRead:
    campaign = await _load_campaign(context, campaign_id)
    await _require_permission(
        context, permission_key="crm.campaign:manage",
        organization_unit_id=campaign.organization_unit_id,
    )
    measurement = await context.session.scalar(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign.id,
            CRMMarketingCampaignMeasurement.measured_on == measured_on,
        ).with_for_update()
    )
    action = "updated"
    if measurement is None:
        measurement = CRMMarketingCampaignMeasurement(
            id=uuid4(),
            tenant_id=context.access.tenant_id,
            organization_unit_id=campaign.organization_unit_id,
            campaign_id=campaign.id,
            measured_on=measured_on,
        )
        context.session.add(measurement)
        action = "recorded"
    for key, value in payload.model_dump().items():
        setattr(measurement, key, value)
    measurement.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit_measurement(context, campaign=campaign, measurement=measurement, action=action)
    await context.session.flush()
    return CampaignMeasurementRead(
        id=measurement.id,
        campaign_id=measurement.campaign_id,
        organization_unit_id=measurement.organization_unit_id,
        measured_on=measurement.measured_on,
        source_label=measurement.source_label,
        impressions=measurement.impressions,
        reach=measurement.reach,
        clicks=measurement.clicks,
        responses=measurement.responses,
        leads=measurement.leads,
        conversions=measurement.conversions,
        assigned_count=measurement.assigned_count,
        exposure_count=measurement.exposure_count,
        return_count=measurement.return_count,
        actual_spend_amount=measurement.actual_spend_amount,
        actual_spend_currency=measurement.actual_spend_currency,
        incentive_cost_amount=measurement.incentive_cost_amount,
        incentive_cost_currency=measurement.incentive_cost_currency,
        refunded_amount=measurement.refunded_amount,
        refunded_currency=measurement.refunded_currency,
        attributed_revenue_amount=measurement.attributed_revenue_amount,
        attributed_revenue_currency=measurement.attributed_revenue_currency,
    )


@router.get(
    "/{campaign_id}/measurements/summary",
    response_model=CampaignMeasurementTotals,
    operation_id="getCRMMarketingCampaignMeasurementSummary",
)
async def get_campaign_measurement_summary(
    campaign_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignMeasurementTotals:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Measurement summaries are limited to 366 calendar days")
    campaign = await _load_campaign(context, campaign_id)
    await _require_permission(
        context, permission_key="crm.campaign:view",
        organization_unit_id=campaign.organization_unit_id,
    )
    rows = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign.id,
            CRMMarketingCampaignMeasurement.measured_on >= period_start,
            CRMMarketingCampaignMeasurement.measured_on <= period_end,
        ).order_by(CRMMarketingCampaignMeasurement.measured_on)
    )).all()

    metric_keys = (
        "impressions", "reach", "clicks", "responses", "leads", "conversions",
        "assigned_count", "exposure_count",
        "return_count",
    )
    totals: dict[str, int | None] = {}
    coverage_days: dict[str, int] = {}
    for key in metric_keys:
        observed = [getattr(row, key) for row in rows if getattr(row, key) is not None]
        coverage_days[key] = len(observed)
        totals[key] = sum(observed) if observed else None

    def paired_rate(numerator_key: str, denominator_key: str) -> float | None:
        paired = [
            (getattr(row, numerator_key), getattr(row, denominator_key))
            for row in rows
            if getattr(row, numerator_key) is not None and getattr(row, denominator_key) is not None
        ]
        numerator = sum(pair[0] for pair in paired)
        denominator = sum(pair[1] for pair in paired)
        return round(100 * numerator / denominator, 4) if paired and denominator > 0 else None

    spend: dict[str, Decimal] = {}
    incentive_cost: dict[str, Decimal] = {}
    refunded: dict[str, Decimal] = {}
    revenue: dict[str, Decimal] = {}
    for row in rows:
        if row.actual_spend_amount is not None and row.actual_spend_currency is not None:
            spend[row.actual_spend_currency] = spend.get(row.actual_spend_currency, Decimal("0")) + row.actual_spend_amount
        if row.incentive_cost_amount is not None and row.incentive_cost_currency is not None:
            incentive_cost[row.incentive_cost_currency] = (
                incentive_cost.get(row.incentive_cost_currency, Decimal("0"))
                + row.incentive_cost_amount
            )
        if row.refunded_amount is not None and row.refunded_currency is not None:
            refunded[row.refunded_currency] = (
                refunded.get(row.refunded_currency, Decimal("0")) + row.refunded_amount
            )
        if row.attributed_revenue_amount is not None and row.attributed_revenue_currency is not None:
            revenue[row.attributed_revenue_currency] = revenue.get(row.attributed_revenue_currency, Decimal("0")) + row.attributed_revenue_amount

    return CampaignMeasurementTotals(
        period_start=period_start,
        period_end=period_end,
        record_count=len(rows),
        source_labels=sorted({row.source_label for row in rows}),
        coverage_days=coverage_days,
        totals=totals,
        click_through_rate_percent=paired_rate("clicks", "impressions"),
        lead_rate_per_click_percent=paired_rate("leads", "clicks"),
        conversion_rate_per_click_percent=paired_rate("conversions", "clicks"),
        actual_spend_by_currency=spend,
        incentive_cost_by_currency=incentive_cost,
        refunded_amount_by_currency=refunded,
        attributed_revenue_by_currency=revenue,
    )


class CampaignBudgetConsumption(BaseModel):
    planned_amount: Decimal | None
    currency: str | None
    measured_spend_in_budget_currency: Decimal | None
    remaining_amount: Decimal | None
    consumed_percent: float | None
    spend_in_other_currencies: dict[str, Decimal]


class CampaignPerformanceItem(BaseModel):
    campaign_id: UUID
    name: str
    status: str
    channel: str
    objective_key: str
    planned_budget_amount: Decimal | None
    planned_budget_currency: str | None
    record_count: int
    source_labels: list[str]
    coverage_days: dict[str, int]
    totals: dict[str, int | None]
    click_through_rate_percent: float | None
    lead_rate_per_click_percent: float | None
    conversion_rate_per_click_percent: float | None
    actual_spend_by_currency: dict[str, Decimal]
    attributed_revenue_by_currency: dict[str, Decimal]
    budget_consumption: CampaignBudgetConsumption
    rate_bases: dict[str, dict[str, int]]


class CampaignPerformancePortfolioRead(BaseModel):
    period_start: date
    period_end: date
    campaign_count: int
    measured_campaign_count: int
    items: list[CampaignPerformanceItem]
    truncated: bool


@router.get(
    "/performance",
    response_model=CampaignPerformancePortfolioRead,
    operation_id="getCRMMarketingCampaignPerformancePortfolio",
    summary="Compare campaign outcomes in an authorized organization scope",
)
async def get_campaign_performance_portfolio(
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignPerformancePortfolioRead:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Performance portfolios are limited to 366 calendar days")

    tenant_id = context.access.tenant_id
    scoped_organization_ids = crm_scope_ids(context, permission_key="crm.campaign:view")
    campaign_rows = (await context.session.scalars(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == tenant_id,
            CRMMarketingCampaign.organization_unit_id.in_(scoped_organization_ids),
        ).order_by(CRMMarketingCampaign.name, CRMMarketingCampaign.id).limit(501)
    )).all()
    truncated = len(campaign_rows) > 500
    campaigns = campaign_rows[:500]
    campaign_ids = [campaign.id for campaign in campaigns]
    measurements = []
    if campaign_ids:
        measurements = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == tenant_id,
                CRMMarketingCampaignMeasurement.campaign_id.in_(campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= period_start,
                CRMMarketingCampaignMeasurement.measured_on <= period_end,
            ).order_by(CRMMarketingCampaignMeasurement.campaign_id,
                       CRMMarketingCampaignMeasurement.measured_on)
        )).all()

    by_campaign: dict[UUID, list[CRMMarketingCampaignMeasurement]] = {
        campaign_id: [] for campaign_id in campaign_ids
    }
    for row in measurements:
        by_campaign[row.campaign_id].append(row)

    metric_keys = (
        "impressions", "reach", "clicks", "responses", "leads", "conversions",
        "assigned_count", "exposure_count", "return_count",
    )

    def currency_totals(rows, amount_key: str, currency_key: str) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for row in rows:
            amount = getattr(row, amount_key)
            currency = getattr(row, currency_key)
            if amount is not None and currency is not None:
                totals[currency] = totals.get(currency, Decimal("0")) + amount
        return totals

    items: list[CampaignPerformanceItem] = []
    for campaign in campaigns:
        rows = by_campaign[campaign.id]
        totals: dict[str, int | None] = {}
        coverage: dict[str, int] = {}
        for key in metric_keys:
            observed = [getattr(row, key) for row in rows if getattr(row, key) is not None]
            coverage[key] = len(observed)
            totals[key] = sum(observed) if observed else None

        def paired_rate(numerator_key: str, denominator_key: str) -> float | None:
            paired = [
                (getattr(row, numerator_key), getattr(row, denominator_key))
                for row in rows
                if getattr(row, numerator_key) is not None
                and getattr(row, denominator_key) is not None
            ]
            denominator = sum(pair[1] for pair in paired)
            return round(100 * sum(pair[0] for pair in paired) / denominator, 4) if paired and denominator else None

        def paired_totals(numerator_key: str, denominator_key: str) -> dict[str, int]:
            paired = [
                (getattr(row, numerator_key), getattr(row, denominator_key))
                for row in rows
                if getattr(row, numerator_key) is not None
                and getattr(row, denominator_key) is not None
            ]
            if not paired:
                return {}
            return {
                "numerator": sum(pair[0] for pair in paired),
                "denominator": sum(pair[1] for pair in paired),
            }

        spend_by_currency = currency_totals(rows, "actual_spend_amount", "actual_spend_currency")
        matching_spend = (
            spend_by_currency.get(campaign.planned_budget_currency)
            if campaign.planned_budget_currency is not None
            else None
        )
        remaining_budget = (
            campaign.planned_budget_amount - matching_spend
            if campaign.planned_budget_amount is not None and matching_spend is not None
            else None
        )
        budget_consumption = CampaignBudgetConsumption(
            planned_amount=campaign.planned_budget_amount,
            currency=campaign.planned_budget_currency,
            measured_spend_in_budget_currency=matching_spend,
            remaining_amount=remaining_budget,
            consumed_percent=(
                round(float(100 * matching_spend / campaign.planned_budget_amount), 4)
                if matching_spend is not None and campaign.planned_budget_amount not in (None, Decimal("0"))
                else None
            ),
            spend_in_other_currencies={
                currency: amount
                for currency, amount in spend_by_currency.items()
                if currency != campaign.planned_budget_currency
            },
        )
        items.append(CampaignPerformanceItem(
            campaign_id=campaign.id,
            name=campaign.name,
            status=campaign.status,
            channel=campaign.channel,
            objective_key=campaign.objective_key,
            planned_budget_amount=campaign.planned_budget_amount,
            planned_budget_currency=campaign.planned_budget_currency,
            record_count=len(rows),
            source_labels=sorted({row.source_label for row in rows}),
            coverage_days=coverage,
            totals=totals,
            click_through_rate_percent=paired_rate("clicks", "impressions"),
            lead_rate_per_click_percent=paired_rate("leads", "clicks"),
            conversion_rate_per_click_percent=paired_rate("conversions", "clicks"),
            actual_spend_by_currency=spend_by_currency,
            attributed_revenue_by_currency=currency_totals(rows, "attributed_revenue_amount", "attributed_revenue_currency"),
            budget_consumption=budget_consumption,
            rate_bases={
                "click_through_rate_percent": paired_totals("clicks", "impressions"),
                "lead_rate_per_click_percent": paired_totals("leads", "clicks"),
                "conversion_rate_per_click_percent": paired_totals("conversions", "clicks"),
            },
        ))

    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign.performance_portfolio_viewed",
        target_type="crm_marketing_campaign_performance_portfolio",
        target_key="organization_scope",
        organization_unit_id=None,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "campaign_count": len(campaigns),
            "measured_campaign_count": sum(bool(by_campaign[campaign.id]) for campaign in campaigns),
            "truncated": truncated,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignPerformancePortfolioRead(
        period_start=period_start,
        period_end=period_end,
        campaign_count=len(campaigns),
        measured_campaign_count=sum(bool(by_campaign[campaign.id]) for campaign in campaigns),
        items=items,
        truncated=truncated,
    )


class CampaignMetricComparison(BaseModel):
    current_value: float | None
    previous_value: float | None
    delta: float | None
    change_percent: float | None


class CampaignAmountComparison(BaseModel):
    current_value: Decimal | None
    previous_value: Decimal | None
    delta: Decimal | None
    change_percent: float | None


class CampaignPerformanceComparisonItem(BaseModel):
    campaign_id: UUID
    name: str
    current: CampaignPerformanceItem | None
    previous: CampaignPerformanceItem | None
    count_metrics: dict[str, CampaignMetricComparison]
    rate_metrics: dict[str, CampaignMetricComparison]
    spend_by_currency: dict[str, CampaignAmountComparison]
    revenue_by_currency: dict[str, CampaignAmountComparison]


class CampaignPerformanceComparisonRead(BaseModel):
    current_period_start: date
    current_period_end: date
    previous_period_start: date
    previous_period_end: date
    period_days: int
    campaign_count: int
    items: list[CampaignPerformanceComparisonItem]
    truncated: bool


def _metric_comparison(current: float | None, previous: float | None) -> CampaignMetricComparison:
    if current is None or previous is None:
        return CampaignMetricComparison(
            current_value=current, previous_value=previous, delta=None, change_percent=None
        )
    delta = current - previous
    return CampaignMetricComparison(
        current_value=current,
        previous_value=previous,
        delta=delta,
        change_percent=round(100 * delta / previous, 4) if previous != 0 else None,
    )


@router.get(
    "/performance/compare",
    response_model=CampaignPerformanceComparisonRead,
    operation_id="compareCRMMarketingCampaignPerformancePeriods",
    summary="Compare equal-length campaign performance periods",
)
async def compare_campaign_performance_periods(
    current_start: date = Query(...),
    current_end: date = Query(...),
    previous_start: date = Query(...),
    previous_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignPerformanceComparisonRead:
    if current_start > current_end or previous_start > previous_end:
        raise HTTPException(status_code=422, detail="Each period start must not be after its end")
    current_days = (current_end - current_start).days
    previous_days = (previous_end - previous_start).days
    if current_days > 365 or previous_days > 365:
        raise HTTPException(status_code=422, detail="Each comparison period is limited to 366 calendar days")
    if current_days != previous_days:
        raise HTTPException(status_code=422, detail="Comparison periods must have equal lengths")

    current = await get_campaign_performance_portfolio(
        period_start=current_start, period_end=current_end, context=context
    )
    previous = await get_campaign_performance_portfolio(
        period_start=previous_start, period_end=previous_end, context=context
    )
    current_by_id = {item.campaign_id: item for item in current.items}
    previous_by_id = {item.campaign_id: item for item in previous.items}
    count_keys = (
        "impressions", "reach", "clicks", "responses", "leads", "conversions",
        "assigned_count", "exposure_count", "return_count",
    )
    rate_keys = (
        "click_through_rate_percent", "lead_rate_per_click_percent",
        "conversion_rate_per_click_percent",
    )
    items: list[CampaignPerformanceComparisonItem] = []
    for campaign_id in current_by_id.keys() | previous_by_id.keys():
        current_item = current_by_id.get(campaign_id)
        previous_item = previous_by_id.get(campaign_id)
        item = current_item or previous_item
        assert item is not None
        current_counts = current_item.totals if current_item else {}
        previous_counts = previous_item.totals if previous_item else {}
        current_rates = current_item.model_dump() if current_item else {}
        previous_rates = previous_item.model_dump() if previous_item else {}

        def compare_currency(metric_key: str) -> dict[str, CampaignAmountComparison]:
            current_amounts = getattr(current_item, metric_key) if current_item else {}
            previous_amounts = getattr(previous_item, metric_key) if previous_item else {}
            comparisons: dict[str, CampaignAmountComparison] = {}
            for currency in sorted(current_amounts.keys() | previous_amounts.keys()):
                current_amount = current_amounts.get(currency)
                previous_amount = previous_amounts.get(currency)
                delta = (
                    current_amount - previous_amount
                    if current_amount is not None and previous_amount is not None
                    else None
                )
                comparisons[currency] = CampaignAmountComparison(
                    current_value=current_amount,
                    previous_value=previous_amount,
                    delta=delta,
                    change_percent=(
                        round(float(100 * delta / previous_amount), 4)
                        if delta is not None and previous_amount != 0
                        else None
                    ),
                )
            return comparisons

        count_comparisons = {
            key: _metric_comparison(
                float(current_counts[key]) if current_counts.get(key) is not None else None,
                float(previous_counts[key]) if previous_counts.get(key) is not None else None,
            )
            for key in count_keys
        }
        rate_comparisons = {
            key: _metric_comparison(
                float(current_rates[key]) if current_rates.get(key) is not None else None,
                float(previous_rates[key]) if previous_rates.get(key) is not None else None,
            )
            for key in rate_keys
        }
        items.append(CampaignPerformanceComparisonItem(
            campaign_id=campaign_id,
            name=item.name,
            current=current_item,
            previous=previous_item,
            count_metrics=count_comparisons,
            rate_metrics=rate_comparisons,
            spend_by_currency=compare_currency("actual_spend_by_currency"),
            revenue_by_currency=compare_currency("attributed_revenue_by_currency"),
        ))

    return CampaignPerformanceComparisonRead(
        current_period_start=current_start,
        current_period_end=current_end,
        previous_period_start=previous_start,
        previous_period_end=previous_end,
        period_days=current_days + 1,
        campaign_count=len(items),
        items=items,
        truncated=current.truncated or previous.truncated,
    )


class CampaignChannelPerformanceItem(BaseModel):
    channel: str
    campaign_count: int
    measured_campaign_count: int
    source_labels: list[str]
    coverage_days: dict[str, int]
    totals: dict[str, int | None]
    rate_bases: dict[str, dict[str, int]]
    click_through_rate_percent: float | None
    lead_rate_per_click_percent: float | None
    conversion_rate_per_click_percent: float | None
    planned_budget_by_currency: dict[str, Decimal]
    actual_spend_by_currency: dict[str, Decimal]
    attributed_revenue_by_currency: dict[str, Decimal]


class CampaignChannelPerformanceRead(BaseModel):
    period_start: date
    period_end: date
    channel_count: int
    measured_campaign_count: int
    items: list[CampaignChannelPerformanceItem]
    truncated: bool


@router.get(
    "/performance/channels",
    response_model=CampaignChannelPerformanceRead,
    operation_id="getCRMMarketingCampaignChannelPerformance",
    summary="Compare campaign outcomes grouped by channel",
)
async def get_campaign_channel_performance(
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignChannelPerformanceRead:
    portfolio = await get_campaign_performance_portfolio(
        period_start=period_start, period_end=period_end, context=context
    )
    groups: dict[str, list[CampaignPerformanceItem]] = {}
    for item in portfolio.items:
        groups.setdefault(item.channel, []).append(item)

    metric_keys = (
        "impressions", "reach", "clicks", "responses", "leads", "conversions",
        "assigned_count", "exposure_count", "return_count",
    )
    rate_keys = (
        "click_through_rate_percent", "lead_rate_per_click_percent",
        "conversion_rate_per_click_percent",
    )
    result_items: list[CampaignChannelPerformanceItem] = []
    for channel, campaigns in sorted(groups.items()):
        totals: dict[str, int | None] = {}
        coverage: dict[str, int] = {}
        for key in metric_keys:
            values = [item.totals[key] for item in campaigns if item.totals[key] is not None]
            totals[key] = sum(values) if values else None
            coverage[key] = sum(item.coverage_days[key] for item in campaigns)

        rate_bases: dict[str, dict[str, int]] = {}
        rates: dict[str, float | None] = {}
        for key in rate_keys:
            bases = [
                item.rate_bases[key]
                for item in campaigns
                if item.rate_bases.get(key)
            ]
            if bases:
                numerator = sum(item["numerator"] for item in bases)
                denominator = sum(item["denominator"] for item in bases)
                rate_bases[key] = {"numerator": numerator, "denominator": denominator}
                rates[key] = round(100 * numerator / denominator, 4) if denominator else None
            else:
                rate_bases[key] = {}
                rates[key] = None

        def sum_currency_map(attribute: str) -> dict[str, Decimal]:
            result: dict[str, Decimal] = {}
            for campaign in campaigns:
                for currency, amount in getattr(campaign, attribute).items():
                    result[currency] = result.get(currency, Decimal("0")) + amount
            return result

        planned_budget_by_currency: dict[str, Decimal] = {}
        for campaign in campaigns:
            if campaign.planned_budget_amount is not None and campaign.planned_budget_currency is not None:
                currency = campaign.planned_budget_currency
                planned_budget_by_currency[currency] = (
                    planned_budget_by_currency.get(currency, Decimal("0"))
                    + campaign.planned_budget_amount
                )

        result_items.append(CampaignChannelPerformanceItem(
            channel=channel,
            campaign_count=len(campaigns),
            measured_campaign_count=sum(campaign.record_count > 0 for campaign in campaigns),
            source_labels=sorted({label for campaign in campaigns for label in campaign.source_labels}),
            coverage_days=coverage,
            totals=totals,
            rate_bases=rate_bases,
            click_through_rate_percent=rates["click_through_rate_percent"],
            lead_rate_per_click_percent=rates["lead_rate_per_click_percent"],
            conversion_rate_per_click_percent=rates["conversion_rate_per_click_percent"],
            planned_budget_by_currency=planned_budget_by_currency,
            actual_spend_by_currency=sum_currency_map("actual_spend_by_currency"),
            attributed_revenue_by_currency=sum_currency_map("attributed_revenue_by_currency"),
        ))

    return CampaignChannelPerformanceRead(
        period_start=period_start,
        period_end=period_end,
        channel_count=len(result_items),
        measured_campaign_count=sum(item.measured_campaign_count for item in result_items),
        items=result_items,
        truncated=portfolio.truncated,
    )
