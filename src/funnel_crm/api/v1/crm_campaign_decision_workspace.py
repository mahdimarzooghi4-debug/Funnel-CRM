"""Evidence-backed decision workspace for one campaign target plan."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, tuple_

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_metric_catalog import MetricDefinition, get_metric_definition
from funnel_crm.api.v1.crm_campaign_targets import (
    CampaignTargetRead,
    evaluate_plan_metrics,
)
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMProductCommerceEvent,
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
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    observed_paid_to_spend_multiple: Decimal | None


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
    metrics: dict[str, DecisionMetric]
    metric_definitions: dict[str, MetricDefinition]
    coverage_definition: MetricDefinition
    commerce_outcomes_by_currency: list[DecisionCommerceCurrency]
    interpretation: str
    causal_attribution_applied: bool
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
            paid_order_count=state.get("paid_order_count", 0),
            paid_amount=paid_amount,
            refund_event_count=state.get("refund_event_count", 0),
            refunded_order_count=state.get("refunded_order_count", 0),
            refunded_amount=state.get("refunded_amount", Decimal("0")),
            observed_paid_to_spend_multiple=ratio,
        ))

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
        metrics=metrics,
        metric_definitions=metric_definitions,
        coverage_definition=coverage_definition,
        commerce_outcomes_by_currency=currency_metrics,
        interpretation=(
            "Metrics support manager review and do not issue an automatic pause, continue, "
            "budget, or channel recommendation."
        ),
        causal_attribution_applied=False,
        automatic_recommendation_issued=False,
    )
