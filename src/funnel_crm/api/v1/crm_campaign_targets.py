"""Manager-entered campaign goals and actual-versus-target evaluation."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaigns", tags=["CRM campaign targets"])


class CampaignTargetWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    impressions_target: int | None = Field(default=None, ge=0)
    clicks_target: int | None = Field(default=None, ge=0)
    leads_target: int | None = Field(default=None, ge=0)
    conversions_target: int | None = Field(default=None, ge=0)
    max_spend_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    max_spend_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    max_cpl_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    cpl_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    max_cost_per_conversion_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    conversion_cost_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    min_roas: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    roas_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def validate_goals(self) -> "CampaignTargetWrite":
        if self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        if (self.period_end - self.period_start).days >= 366:
            raise ValueError("target period cannot exceed 366 days")
        goals = (
            self.impressions_target, self.clicks_target, self.leads_target,
            self.conversions_target, self.max_spend_amount, self.max_cpl_amount,
            self.max_cost_per_conversion_amount, self.min_roas,
        )
        if all(value is None for value in goals):
            raise ValueError("at least one campaign target is required")
        for amount, currency, label in (
            (self.max_spend_amount, self.max_spend_currency, "spend"),
            (self.max_cpl_amount, self.cpl_currency, "CPL"),
            (self.max_cost_per_conversion_amount, self.conversion_cost_currency, "cost per conversion"),
            (self.min_roas, self.roas_currency, "ROAS"),
        ):
            if (amount is None) != (currency is None):
                raise ValueError(f"{label} target amount and currency must be provided together")
        return self


class CampaignTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    organization_unit_id: UUID
    period_start: date
    period_end: date
    impressions_target: int | None
    clicks_target: int | None
    leads_target: int | None
    conversions_target: int | None
    max_spend_amount: Decimal | None
    max_spend_currency: str | None
    max_cpl_amount: Decimal | None
    cpl_currency: str | None
    max_cost_per_conversion_amount: Decimal | None
    conversion_cost_currency: str | None
    min_roas: Decimal | None
    roas_currency: str | None
    created_at: datetime
    updated_at: datetime


class TargetMetricEvaluation(BaseModel):
    target: int | Decimal
    actual: int | Decimal | None
    status: str
    currency: str | None = None
    observed_days: int
    paired_days: int = 0
    period_days: int
    recorded_day_coverage_percent: Decimal


class CampaignTargetEvaluation(BaseModel):
    target_plan: CampaignTargetRead
    metrics: dict[str, TargetMetricEvaluation]


async def _campaign(
    context: TenantSessionContext, campaign_id: UUID, permission: str
) -> CRMMarketingCampaign:
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="CRM campaign not found")
    if not await has_crm_permission(
        context, permission_key=permission,
        organization_unit_id=campaign.organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="Campaign action is not authorized for this organization scope")
    return campaign


def _result(target: int | Decimal, actual: int | Decimal | None, *, lower_is_better: bool,
            currency: str | None, observed_days: int, period_days: int,
            paired_days: int = 0) -> TargetMetricEvaluation:
    if actual is None:
        result = "no_data"
    elif (actual <= target if lower_is_better else actual >= target):
        result = "met"
    else:
        result = "not_met"
    return TargetMetricEvaluation(
        target=target, actual=actual, status=result, currency=currency,
        observed_days=observed_days, paired_days=paired_days, period_days=period_days,
        recorded_day_coverage_percent=(
            (Decimal(observed_days) * Decimal("100") / Decimal(period_days)).quantize(Decimal("0.01"))
            if period_days > 0 else Decimal("0")
        ),
    )


def evaluate_plan_metrics(
    plan: CRMMarketingCampaignTargetPlan,
    rows: list[CRMMarketingCampaignMeasurement],
) -> dict[str, TargetMetricEvaluation]:
    """Evaluate one plan using only observed and currency-compatible measurement rows."""
    metrics: dict[str, TargetMetricEvaluation] = {}
    period_days = (plan.period_end - plan.period_start).days + 1
    for name, target_attr, data_attr in (
        ("impressions", "impressions_target", "impressions"),
        ("clicks", "clicks_target", "clicks"),
        ("leads", "leads_target", "leads"),
        ("conversions", "conversions_target", "conversions"),
    ):
        target = getattr(plan, target_attr)
        if target is not None:
            values = [getattr(row, data_attr) for row in rows if getattr(row, data_attr) is not None]
            metrics[name] = _result(target, sum(values) if values else None,
                                    lower_is_better=False, currency=None, observed_days=len(values), period_days=period_days)
    if plan.max_spend_amount is not None:
        matching = [row for row in rows if row.actual_spend_amount is not None
                    and row.actual_spend_currency == plan.max_spend_currency]
        actual = sum((row.actual_spend_amount for row in matching), Decimal("0")) if matching else None
        metrics["spend"] = _result(plan.max_spend_amount, actual, lower_is_better=True,
                                   currency=plan.max_spend_currency, observed_days=len(matching))
    for key, target, currency, outcome_attr in (
        ("cost_per_lead", plan.max_cpl_amount, plan.cpl_currency, "leads"),
        ("cost_per_conversion", plan.max_cost_per_conversion_amount,
         plan.conversion_cost_currency, "conversions"),
    ):
        if target is None:
            continue
        paired = [row for row in rows if row.actual_spend_amount is not None
                  and row.actual_spend_currency == currency and getattr(row, outcome_attr) is not None]
        spend = sum((row.actual_spend_amount for row in paired), Decimal("0"))
        outcomes = sum((getattr(row, outcome_attr) for row in paired), 0)
        actual = (spend / Decimal(outcomes)).quantize(Decimal("0.000001")) if paired and outcomes > 0 else None
        metrics[key] = _result(target, actual, lower_is_better=True, currency=currency,
                               observed_days=len(paired), paired_days=len(paired))
    if plan.min_roas is not None:
        paired = [row for row in rows if row.actual_spend_amount is not None
                  and row.actual_spend_currency == plan.roas_currency
                  and row.attributed_revenue_amount is not None
                  and row.attributed_revenue_currency == plan.roas_currency]
        spend = sum((row.actual_spend_amount for row in paired), Decimal("0"))
        revenue = sum((row.attributed_revenue_amount for row in paired), Decimal("0"))
        actual = (revenue / spend).quantize(Decimal("0.000001")) if paired and spend > 0 else None
        metrics["roas"] = _result(plan.min_roas, actual, lower_is_better=False,
                                  currency=plan.roas_currency, observed_days=len(paired), period_days=period_days,
                                  paired_days=len(paired))
    return metrics


@router.put("/{campaign_id}/targets", response_model=CampaignTargetRead,
            operation_id="setCRMMarketingCampaignTargets")
async def set_campaign_targets(
    campaign_id: UUID,
    payload: CampaignTargetWrite,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignTargetRead:
    campaign = await _campaign(context, campaign_id, "crm.campaign:manage")
    plan = await context.session.scalar(
        select(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.campaign_id == campaign_id,
            CRMMarketingCampaignTargetPlan.period_start == payload.period_start,
            CRMMarketingCampaignTargetPlan.period_end == payload.period_end,
        ).with_for_update()
    )
    values = payload.model_dump()
    if plan is None:
        plan = CRMMarketingCampaignTargetPlan(
            id=uuid4(), tenant_id=context.access.tenant_id,
            organization_unit_id=campaign.organization_unit_id,
            campaign_id=campaign.id, **values,
        )
        context.session.add(plan)
        action = "crm_marketing_campaign_target_plan.created"
        before = None
    else:
        before = {
            key: getattr(plan, key).isoformat() if isinstance(getattr(plan, key), date)
            else str(getattr(plan, key)) if getattr(plan, key) is not None else None
            for key in values
        }
        for key, value in values.items():
            setattr(plan, key, value)
        plan.updated_at = datetime.now(timezone.utc)
        action = "crm_marketing_campaign_target_plan.updated"
    await context.session.flush()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key=action, target_type="crm_marketing_campaign_target_plan",
        target_key=str(plan.id), organization_unit_id=campaign.organization_unit_id,
        before_state=before,
        after_state={key: value.isoformat() if isinstance(value, date) else str(value) if value is not None else None
                     for key, value in values.items()},
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignTargetRead.model_validate(plan)


@router.get("/{campaign_id}/targets", response_model=list[CampaignTargetRead],
            operation_id="listCRMMarketingCampaignTargets")
async def list_campaign_targets(
    campaign_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[CampaignTargetRead]:
    await _campaign(context, campaign_id, "crm.campaign:view")
    plans = (await context.session.scalars(
        select(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.campaign_id == campaign_id,
        ).order_by(CRMMarketingCampaignTargetPlan.period_start, CRMMarketingCampaignTargetPlan.period_end)
    )).all()
    return [CampaignTargetRead.model_validate(plan) for plan in plans]


@router.get("/{campaign_id}/targets/{target_id}/evaluation",
            response_model=CampaignTargetEvaluation,
            operation_id="evaluateCRMMarketingCampaignTargets")
async def evaluate_campaign_targets(
    campaign_id: UUID,
    target_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignTargetEvaluation:
    campaign = await _campaign(context, campaign_id, "crm.campaign:view")
    plan = await context.session.scalar(
        select(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.campaign_id == campaign_id,
            CRMMarketingCampaignTargetPlan.id == target_id,
            CRMMarketingCampaignTargetPlan.organization_unit_id == campaign.organization_unit_id,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Campaign target plan not found")
    rows = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign_id,
            CRMMarketingCampaignMeasurement.measured_on >= plan.period_start,
            CRMMarketingCampaignMeasurement.measured_on <= plan.period_end,
        ).order_by(CRMMarketingCampaignMeasurement.measured_on)
    )).all()
    metrics = evaluate_plan_metrics(plan, rows)
    return CampaignTargetEvaluation(target_plan=CampaignTargetRead.model_validate(plan), metrics=metrics)
