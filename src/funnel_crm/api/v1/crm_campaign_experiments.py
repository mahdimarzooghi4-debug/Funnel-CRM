"""Plan and describe campaign variant experiments without claiming causality."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignExperiment,
    CRMMarketingCampaignExperimentVariant,
    CRMMarketingCampaignMeasurement,
    CRMProfileSegment,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaign-experiments", tags=["CRM marketing experiments"])
ExperimentMetric = Literal[
    "impressions", "clicks", "leads", "conversions",
    "click_through_rate_percent", "conversion_rate_per_click_percent",
    "cost_per_lead", "cost_per_conversion", "roas",
]
COUNT_METRICS = {"impressions", "clicks", "leads", "conversions"}
CURRENCY_METRICS = {"cost_per_lead", "cost_per_conversion", "roas"}


class ExperimentVariantWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    label: str = Field(min_length=1, max_length=80)
    is_control: bool = False

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must contain a non-whitespace character")
        return value


class GuardrailMetricWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: ExperimentMetric
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def validate_currency(self):
        if (self.metric in CURRENCY_METRICS) != (self.currency is not None):
            raise ValueError("currency is required only for cost and ROAS guardrails")
        return self


class CampaignExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    name: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=1, max_length=1000)
    primary_metric: ExperimentMetric
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    period_start: date
    period_end: date
    variants: list[ExperimentVariantWrite] = Field(min_length=2, max_length=6)
    guardrails: list[GuardrailMetricWrite] = Field(default_factory=list, max_length=8)
    allocation_method: str = Field(min_length=1, max_length=250)
    known_limitations: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "hypothesis", "allocation_method")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must contain a non-whitespace character")
        return value

    @field_validator("known_limitations")
    @classmethod
    def normalize_limitations(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("known limitations must be omitted or contain text")
        return value

    @model_validator(mode="after")
    def validate_experiment(self) -> "CampaignExperimentCreate":
        if self.period_start > self.period_end or (self.period_end - self.period_start).days >= 366:
            raise ValueError("period must be ordered and no longer than 366 days")
        if (self.primary_metric in CURRENCY_METRICS) != (self.currency is not None):
            raise ValueError("currency is required only for cost and ROAS metrics")
        if len({variant.campaign_id for variant in self.variants}) != len(self.variants):
            raise ValueError("each variant must use a different campaign")
        if sum(variant.is_control for variant in self.variants) != 1:
            raise ValueError("exactly one control variant is required")
        guardrail_keys = [(item.metric, item.currency) for item in self.guardrails]
        if len(set(guardrail_keys)) != len(guardrail_keys):
            raise ValueError("guardrail metrics must be unique")
        if (self.primary_metric, self.currency) in set(guardrail_keys):
            raise ValueError("primary metric cannot also be a guardrail")
        return self


class CampaignExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    name: str
    hypothesis: str
    primary_metric: str
    currency: str | None
    guardrail_metrics: list[dict[str, str | None]]
    allocation_method: str
    known_limitations: str | None
    audience_snapshot: dict[str, Any] | None
    period_start: date
    period_end: date
    created_at: datetime


class ExperimentVariantRead(BaseModel):
    campaign_id: UUID
    campaign_name: str
    label: str
    is_control: bool


class CampaignExperimentListItem(BaseModel):
    experiment: CampaignExperimentRead
    variants: list[ExperimentVariantRead]


class GuardrailMetricReadout(BaseModel):
    metric: ExperimentMetric
    currency: str | None
    value: int | Decimal | None
    delta_vs_control: int | Decimal | None
    percent_change_vs_control: float | None
    status: Literal["available", "no_data"]
    observed_days: int
    paired_days: int


class VariantReadout(BaseModel):
    campaign_id: UUID
    campaign_name: str
    label: str
    is_control: bool
    value: int | Decimal | None
    delta_vs_control: int | Decimal | None
    percent_change_vs_control: float | None
    currency: str | None
    status: Literal["available", "no_data"]
    observed_days: int
    paired_days: int
    guardrails: list[GuardrailMetricReadout] = Field(default_factory=list)


class CampaignExperimentReadout(BaseModel):
    experiment: CampaignExperimentRead
    readout_kind: Literal["descriptive_observation"] = "descriptive_observation"
    variants: list[VariantReadout]


async def _require_permission(
    context: TenantSessionContext, permission: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Campaign experiment is not authorized for this organization scope")


def _metric_value(
    metric: str,
    currency: str | None,
    rows: list[CRMMarketingCampaignMeasurement],
) -> tuple[int | Decimal | None, int, int]:
    if metric in COUNT_METRICS:
        values = [getattr(row, metric) for row in rows if getattr(row, metric) is not None]
        return (sum(values) if values else None, len(values), 0)
    if metric == "click_through_rate_percent":
        paired = [row for row in rows if row.clicks is not None and row.impressions is not None]
        clicks = sum((row.clicks for row in paired), 0)
        impressions = sum((row.impressions for row in paired), 0)
        value = (Decimal(clicks * 100) / Decimal(impressions)).quantize(Decimal("0.0001")) if paired and impressions > 0 else None
        return value, len(paired), len(paired)
    if metric == "conversion_rate_per_click_percent":
        paired = [row for row in rows if row.conversions is not None and row.clicks is not None]
        conversions = sum((row.conversions for row in paired), 0)
        clicks = sum((row.clicks for row in paired), 0)
        value = (Decimal(conversions * 100) / Decimal(clicks)).quantize(Decimal("0.0001")) if paired and clicks > 0 else None
        return value, len(paired), len(paired)
    if metric in {"cost_per_lead", "cost_per_conversion"}:
        outcome = "leads" if metric == "cost_per_lead" else "conversions"
        paired = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and getattr(row, outcome) is not None
        ]
        spend = sum((row.actual_spend_amount for row in paired), Decimal("0"))
        outcomes = sum((getattr(row, outcome) for row in paired), 0)
        value = (spend / Decimal(outcomes)).quantize(Decimal("0.000001")) if paired and outcomes > 0 else None
        return value, len(paired), len(paired)
    if metric == "roas":
        paired = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and row.attributed_revenue_amount is not None and row.attributed_revenue_currency == currency
        ]
        spend = sum((row.actual_spend_amount for row in paired), Decimal("0"))
        revenue = sum((row.attributed_revenue_amount for row in paired), Decimal("0"))
        value = (revenue / spend).quantize(Decimal("0.000001")) if paired and spend > 0 else None
        return value, len(paired), len(paired)
    raise ValueError("Unsupported experiment metric")


@router.post("", response_model=CampaignExperimentRead, status_code=201,
             operation_id="createCRMMarketingCampaignExperiment")
async def create_campaign_experiment(
    payload: CampaignExperimentCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignExperimentRead:
    await _require_permission(context, "crm.campaign:manage", payload.organization_unit_id)
    campaigns = (await context.session.scalars(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.organization_unit_id == payload.organization_unit_id,
            CRMMarketingCampaign.id.in_([variant.campaign_id for variant in payload.variants]),
        )
    )).all()
    if len(campaigns) != len(payload.variants):
        raise HTTPException(status_code=422, detail="All experiment campaigns must exist in the selected organization")
    signatures = {(campaign.segment_id, campaign.objective_key, campaign.channel) for campaign in campaigns}
    if len(signatures) != 1:
        raise HTTPException(
            status_code=422,
            detail="Experiment variants must share the same segment, objective, and channel",
        )
    segment = await context.session.scalar(select(CRMProfileSegment).where(
        CRMProfileSegment.tenant_id == context.access.tenant_id,
        CRMProfileSegment.id == campaigns[0].segment_id,
        CRMProfileSegment.organization_unit_id == payload.organization_unit_id,
    ))
    if segment is None:
        raise HTTPException(status_code=422, detail="The shared experiment audience segment is unavailable")
    audience_snapshot = {
        "segment_id": str(segment.id),
        "segment_name": segment.name,
        "criteria": segment.criteria,
    }

    experiment = CRMMarketingCampaignExperiment(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        name=payload.name, hypothesis=payload.hypothesis,
        primary_metric=payload.primary_metric, currency=payload.currency,
        guardrail_metrics=[item.model_dump() for item in payload.guardrails],
        allocation_method=payload.allocation_method,
        known_limitations=payload.known_limitations,
        audience_snapshot=audience_snapshot,
        period_start=payload.period_start, period_end=payload.period_end,
    )
    context.session.add(experiment)
    await context.session.flush()
    context.session.add_all([
        CRMMarketingCampaignExperimentVariant(
            id=uuid4(), tenant_id=context.access.tenant_id,
            organization_unit_id=payload.organization_unit_id,
            experiment_id=experiment.id, campaign_id=variant.campaign_id,
            label=variant.label, is_control=variant.is_control,
        )
        for variant in payload.variants
    ])
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign_experiment.created",
        target_type="crm_marketing_campaign_experiment",
        target_key=str(experiment.id),
        organization_unit_id=payload.organization_unit_id,
        before_state=None,
        after_state={
            "primary_metric": payload.primary_metric,
            "period_start": payload.period_start.isoformat(),
            "period_end": payload.period_end.isoformat(),
            "variant_count": len(payload.variants),
            "guardrails": [item.model_dump() for item in payload.guardrails],
            "allocation_method": payload.allocation_method,
            "known_limitations": payload.known_limitations,
            "audience_segment_id": str(segment.id),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignExperimentRead.model_validate(experiment)


@router.get("", response_model=list[CampaignExperimentListItem],
            operation_id="listCRMMarketingCampaignExperiments")
async def list_campaign_experiments(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CampaignExperimentListItem]:
    permitted_scopes = crm_scope_ids(context, permission_key="crm.campaign:view")
    if organization_unit_id is not None and organization_unit_id not in permitted_scopes:
        raise HTTPException(status_code=403, detail="Campaign experiment is not authorized for this organization scope")
    statement = (
        select(CRMMarketingCampaignExperiment)
        .where(
            CRMMarketingCampaignExperiment.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignExperiment.organization_unit_id.in_(permitted_scopes),
        )
        .order_by(CRMMarketingCampaignExperiment.created_at.desc(),
                  CRMMarketingCampaignExperiment.id)
    )
    if organization_unit_id is not None:
        statement = statement.where(
            CRMMarketingCampaignExperiment.organization_unit_id == organization_unit_id
        )
    experiments = (await context.session.scalars(statement.limit(limit).offset(offset))).all()
    result: list[CampaignExperimentListItem] = []
    for experiment in experiments:
        variants = (await context.session.execute(
            select(CRMMarketingCampaignExperimentVariant, CRMMarketingCampaign.name)
            .join(CRMMarketingCampaign, CRMMarketingCampaign.id == CRMMarketingCampaignExperimentVariant.campaign_id)
            .where(
                CRMMarketingCampaignExperimentVariant.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignExperimentVariant.experiment_id == experiment.id,
            )
            .order_by(CRMMarketingCampaignExperimentVariant.is_control.desc(),
                      CRMMarketingCampaignExperimentVariant.label)
        )).all()
        result.append(CampaignExperimentListItem(
            experiment=CampaignExperimentRead.model_validate(experiment),
            variants=[
                ExperimentVariantRead(
                    campaign_id=variant.campaign_id, campaign_name=campaign_name,
                    label=variant.label, is_control=variant.is_control,
                )
                for variant, campaign_name in variants
            ],
        ))
    return result


@router.get("/{experiment_id}/readout", response_model=CampaignExperimentReadout,
            operation_id="readCRMMarketingCampaignExperiment")
async def read_campaign_experiment(
    experiment_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignExperimentReadout:
    experiment = await context.session.scalar(
        select(CRMMarketingCampaignExperiment).where(
            CRMMarketingCampaignExperiment.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignExperiment.id == experiment_id,
        )
    )
    if experiment is None:
        raise HTTPException(status_code=404, detail="Campaign experiment not found")
    await _require_permission(context, "crm.campaign:view", experiment.organization_unit_id)

    variant_rows = (await context.session.execute(
        select(CRMMarketingCampaignExperimentVariant, CRMMarketingCampaign.name)
        .join(CRMMarketingCampaign, CRMMarketingCampaign.id == CRMMarketingCampaignExperimentVariant.campaign_id)
        .where(
            CRMMarketingCampaignExperimentVariant.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignExperimentVariant.organization_unit_id == experiment.organization_unit_id,
            CRMMarketingCampaignExperimentVariant.experiment_id == experiment.id,
        )
        .order_by(CRMMarketingCampaignExperimentVariant.is_control.desc(),
                  CRMMarketingCampaignExperimentVariant.label)
    )).all()
    campaign_ids = [variant.campaign_id for variant, _ in variant_rows]
    measurements_by_campaign: dict[UUID, list[CRMMarketingCampaignMeasurement]] = {
        campaign_id: [] for campaign_id in campaign_ids
    }
    if campaign_ids:
        measurements = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id == experiment.organization_unit_id,
                CRMMarketingCampaignMeasurement.campaign_id.in_(campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= experiment.period_start,
                CRMMarketingCampaignMeasurement.measured_on <= experiment.period_end,
            ).order_by(CRMMarketingCampaignMeasurement.measured_on)
        )).all()
        for measurement in measurements:
            measurements_by_campaign[measurement.campaign_id].append(measurement)

    control_variant = next((variant for variant, _ in variant_rows if variant.is_control), None)
    control_value: int | Decimal | None = None
    if control_variant is not None:
        control_value, _, _ = _metric_value(
            experiment.primary_metric, experiment.currency,
            measurements_by_campaign[control_variant.campaign_id],
        )
    readouts: list[VariantReadout] = []
    guardrail_configs = experiment.guardrail_metrics or []
    guardrail_controls = {
        (item["metric"], item.get("currency")): _metric_value(
            item["metric"], item.get("currency"),
            measurements_by_campaign[control_variant.campaign_id],
        )[0]
        for item in guardrail_configs
    } if control_variant is not None else {}
    for variant, campaign_name in variant_rows:
        value, observed_days, paired_days = _metric_value(
            experiment.primary_metric, experiment.currency,
            measurements_by_campaign[variant.campaign_id],
        )
        delta = value - control_value if value is not None and control_value is not None else None
        percent = (
            round(float(delta) / abs(float(control_value)) * 100, 4)
            if delta is not None and control_value != 0 else None
        )
        guardrail_readouts = []
        for item in guardrail_configs:
            metric, currency = item["metric"], item.get("currency")
            guard_value, guard_days, guard_paired = _metric_value(
                metric, currency, measurements_by_campaign[variant.campaign_id]
            )
            guard_control = guardrail_controls.get((metric, currency))
            guard_delta = guard_value - guard_control if guard_value is not None and guard_control is not None else None
            guard_percent = (
                round(float(guard_delta) / abs(float(guard_control)) * 100, 4)
                if guard_delta is not None and guard_control != 0 else None
            )
            guardrail_readouts.append(GuardrailMetricReadout(
                metric=metric, currency=currency, value=guard_value,
                delta_vs_control=guard_delta, percent_change_vs_control=guard_percent,
                status="available" if guard_value is not None else "no_data",
                observed_days=guard_days, paired_days=guard_paired,
            ))
        readouts.append(VariantReadout(
            campaign_id=variant.campaign_id, campaign_name=campaign_name,
            label=variant.label, is_control=variant.is_control,
            value=value, delta_vs_control=delta,
            percent_change_vs_control=percent, currency=experiment.currency,
            status="available" if value is not None else "no_data",
            observed_days=observed_days, paired_days=paired_days,
            guardrails=guardrail_readouts,
        ))
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign_experiment.readout_viewed",
        target_type="crm_marketing_campaign_experiment",
        target_key=str(experiment.id),
        organization_unit_id=experiment.organization_unit_id,
        before_state=None,
        after_state={
            "primary_metric": experiment.primary_metric,
            "period_start": experiment.period_start.isoformat(),
            "period_end": experiment.period_end.isoformat(),
            "variant_count": len(readouts),
            "guardrail_count": len(guardrail_configs),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignExperimentReadout(
        experiment=CampaignExperimentRead.model_validate(experiment),
        variants=readouts,
    )
