"""Descriptive sales forecast based on manager-configured stage probabilities."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMOpportunity,
    CRMPipeline,
    OrganizationUnit,
    Workspace,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/sales-forecast", tags=["CRM sales forecasting"])


class StageProbabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probability_percent: int | None = Field(default=None, ge=0, le=100)


class ForecastStage(BaseModel):
    stage_key: str
    stage_name: str
    probability_percent: int | None
    opportunity_count: int
    unpriced_opportunity_count: int
    unknown_probability_opportunity_count: int
    gross_amount_by_currency: dict[str, Decimal]
    weighted_expected_amount_by_currency: dict[str, Decimal]


class SalesForecast(BaseModel):
    pipeline_id: UUID
    organization_unit_id: UUID | None
    period_start: date
    period_end: date
    forecast_basis: str = "manager_configured_stage_probability"
    opportunity_count: int
    priced_opportunity_count: int
    unpriced_opportunity_count: int
    unknown_probability_opportunity_count: int
    unscheduled_opportunity_count: int
    gross_amount_by_currency: dict[str, Decimal]
    weighted_expected_amount_by_currency: dict[str, Decimal]
    amount_without_probability_by_currency: dict[str, Decimal]
    stages: list[ForecastStage]


async def _require(
    context: TenantSessionContext, permission_key: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Sales forecast action is not authorized")


async def _pipeline(
    context: TenantSessionContext, pipeline_id: UUID
) -> CRMPipeline:
    pipeline = await context.session.scalar(select(CRMPipeline).where(
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.id == pipeline_id,
        CRMPipeline.entity_kind == "opportunity",
    ))
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Opportunity pipeline not found")
    return pipeline


@router.patch(
    "/pipelines/{pipeline_id}/stages/{stage_key}/probability",
    operation_id="setCRMOpportunityStageProbability",
)
async def set_stage_probability(
    pipeline_id: UUID,
    stage_key: str,
    payload: StageProbabilityUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict[str, Any]:
    workspace = await context.session.get(Workspace, context.access.tenant_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="CRM workspace not found")
    if not await has_crm_permission(
        context, permission_key="crm.pipeline:manage",
        organization_unit_id=workspace.root_organization_id,
    ):
        raise HTTPException(status_code=403, detail="Pipeline configuration is not authorized")

    pipeline = await context.session.scalar(select(CRMPipeline).where(
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.id == pipeline_id,
        CRMPipeline.entity_kind == "opportunity",
    ).with_for_update())
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Opportunity pipeline not found")
    stage_index = next((
        index for index, stage in enumerate(pipeline.stages)
        if isinstance(stage, dict) and stage.get("key") == stage_key
    ), None)
    if stage_index is None:
        raise HTTPException(status_code=404, detail="Opportunity pipeline stage not found")

    stages = [dict(stage) for stage in pipeline.stages]
    before_probability = stages[stage_index].get("probability_percent")
    stages[stage_index]["probability_percent"] = payload.probability_percent
    pipeline.stages = stages
    pipeline.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity_pipeline.stage_probability_updated",
        target_type="crm_pipeline",
        target_key=str(pipeline.id),
        organization_unit_id=workspace.root_organization_id,
        before_state={"stage_key": stage_key, "probability_percent": before_probability},
        after_state={"stage_key": stage_key, "probability_percent": payload.probability_percent},
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "pipeline_id": pipeline.id,
        "stage_key": stage_key,
        "probability_percent": payload.probability_percent,
    }


@router.get("/opportunities", response_model=SalesForecast,
            operation_id="getCRMOpportunitySalesForecast")
async def get_sales_forecast(
    pipeline_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SalesForecast:
    if period_start > period_end or (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Forecast period must be ordered and no longer than 366 days")
    scopes = crm_scope_ids(context, permission_key="crm.opportunity:view")
    if organization_unit_id is not None:
        await _require(context, "crm.opportunity:view", organization_unit_id)
        scopes = select(OrganizationUnit.id).where(
            OrganizationUnit.tenant_id == context.access.tenant_id,
            OrganizationUnit.id == organization_unit_id,
            OrganizationUnit.id.in_(scopes),
        )
    pipeline = await _pipeline(context, pipeline_id)
    base_filters = [
        CRMOpportunity.tenant_id == context.access.tenant_id,
        CRMOpportunity.pipeline_id == pipeline.id,
        CRMOpportunity.organization_unit_id.in_(scopes),
    ]
    rows = (await context.session.scalars(select(CRMOpportunity).where(
        *base_filters,
        CRMOpportunity.expected_close_date >= period_start,
        CRMOpportunity.expected_close_date <= period_end,
    ).order_by(CRMOpportunity.expected_close_date, CRMOpportunity.id))).all()
    unscheduled_count = int(await context.session.scalar(
        select(func.count()).select_from(CRMOpportunity).where(
            *base_filters, CRMOpportunity.expected_close_date.is_(None)
        )
    ) or 0)

    stage_config = {
        stage["key"]: stage
        for stage in pipeline.stages
        if isinstance(stage, dict) and isinstance(stage.get("key"), str)
    }
    results: list[dict[str, Any]] = []
    total_gross: dict[str, Decimal] = {}
    total_weighted: dict[str, Decimal] = {}
    total_unknown: dict[str, Decimal] = {}
    priced_count = unpriced_count = unknown_probability_count = 0
    for key, config in stage_config.items():
        stage_rows = [row for row in rows if row.stage_key == key]
        probability = config.get("probability_percent")
        if not isinstance(probability, int) or isinstance(probability, bool) or not 0 <= probability <= 100:
            probability = None
        gross: dict[str, Decimal] = {}
        weighted: dict[str, Decimal] = {}
        stage_unpriced = stage_unknown = 0
        for row in stage_rows:
            if row.amount is None or row.currency is None:
                stage_unpriced += 1
                unpriced_count += 1
                continue
            priced_count += 1
            gross[row.currency] = gross.get(row.currency, Decimal("0")) + row.amount
            total_gross[row.currency] = total_gross.get(row.currency, Decimal("0")) + row.amount
            if probability is None:
                stage_unknown += 1
                unknown_probability_count += 1
                total_unknown[row.currency] = total_unknown.get(row.currency, Decimal("0")) + row.amount
                continue
            expected = (row.amount * Decimal(probability) / Decimal(100)).quantize(Decimal("0.000001"))
            weighted[row.currency] = weighted.get(row.currency, Decimal("0")) + expected
            total_weighted[row.currency] = total_weighted.get(row.currency, Decimal("0")) + expected

        results.append({
            "stage_key": key,
            "stage_name": str(config.get("name", key)),
            "probability_percent": probability,
            "opportunity_count": len(stage_rows),
            "unpriced_opportunity_count": stage_unpriced,
            "unknown_probability_opportunity_count": stage_unknown,
            "gross_amount_by_currency": gross,
            "weighted_expected_amount_by_currency": weighted,
        })

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity_forecast.viewed",
        target_type="crm_opportunity_forecast",
        target_key=str(pipeline.id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
            "opportunity_count": len(rows), "unscheduled_opportunity_count": unscheduled_count,
            "organization_unit_id": str(organization_unit_id) if organization_unit_id else None,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return SalesForecast(
        pipeline_id=pipeline.id, organization_unit_id=organization_unit_id,
        period_start=period_start, period_end=period_end,
        opportunity_count=len(rows), priced_opportunity_count=priced_count,
        unpriced_opportunity_count=unpriced_count,
        unknown_probability_opportunity_count=unknown_probability_count,
        unscheduled_opportunity_count=unscheduled_count,
        gross_amount_by_currency=total_gross,
        weighted_expected_amount_by_currency=total_weighted,
        amount_without_probability_by_currency=total_unknown,
        stages=results,
    )
