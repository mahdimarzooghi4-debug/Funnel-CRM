"""Capture and aggregate observed daily campaign measurements."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
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
