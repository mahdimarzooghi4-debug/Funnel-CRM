"""Descriptive sales forecast based on manager-configured stage probabilities."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
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
    outcome_key: str
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
    closed_won_count: int
    closed_lost_count: int
    priced_opportunity_count: int
    unpriced_opportunity_count: int
    unknown_probability_opportunity_count: int
    unscheduled_opportunity_count: int
    gross_amount_by_currency: dict[str, Decimal]
    weighted_expected_amount_by_currency: dict[str, Decimal]
    amount_without_probability_by_currency: dict[str, Decimal]
    stages: list[ForecastStage]


class SalesOutcomeBucket(BaseModel):
    pipeline_id: UUID
    outcome_key: Literal["won", "lost"]
    stage_key: str
    stage_name: str
    outcome_count: int
    priced_outcome_count: int
    unpriced_outcome_count: int
    amount_by_currency: dict[str, Decimal]


class SalesOutcomeReport(BaseModel):
    period_start: date
    period_end: date
    pipeline_id: UUID | None
    organization_unit_id: UUID | None
    basis: str = "recorded_terminal_stage_transition"
    won_count: int
    lost_count: int
    won_amount_by_currency: dict[str, Decimal]
    lost_amount_by_currency: dict[str, Decimal]
    buckets: list[SalesOutcomeBucket]


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
    unscheduled_rows = (await context.session.scalars(select(CRMOpportunity).where(
        *base_filters, CRMOpportunity.expected_close_date.is_(None)
    ))).all()

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
    closed_won_count = closed_lost_count = 0
    for key, config in stage_config.items():
        stage_rows = [row for row in rows if row.stage_key == key]
        outcome_key = config.get("outcome_key", "open")
        if outcome_key not in ("open", "won", "lost"):
            outcome_key = "open"
        if outcome_key == "won":
            closed_won_count += len(stage_rows)
        elif outcome_key == "lost":
            closed_lost_count += len(stage_rows)
        probability = config.get("probability_percent")
        if not isinstance(probability, int) or isinstance(probability, bool) or not 0 <= probability <= 100:
            probability = None
        gross: dict[str, Decimal] = {}
        weighted: dict[str, Decimal] = {}
        stage_unpriced = 0
        stage_unknown = len(stage_rows) if probability is None and outcome_key == "open" else 0
        if outcome_key == "open":
            unknown_probability_count += stage_unknown
        for row in stage_rows if outcome_key == "open" else []:
            if row.amount is None or row.currency is None:
                stage_unpriced += 1
                unpriced_count += 1
                continue
            priced_count += 1
            gross[row.currency] = gross.get(row.currency, Decimal("0")) + row.amount
            total_gross[row.currency] = total_gross.get(row.currency, Decimal("0")) + row.amount
            if probability is None:
                total_unknown[row.currency] = total_unknown.get(row.currency, Decimal("0")) + row.amount
                continue
            expected = (row.amount * Decimal(probability) / Decimal(100)).quantize(Decimal("0.000001"))
            weighted[row.currency] = weighted.get(row.currency, Decimal("0")) + expected
            total_weighted[row.currency] = total_weighted.get(row.currency, Decimal("0")) + expected

        results.append({
            "stage_key": key,
            "stage_name": str(config.get("name", key)),
            "outcome_key": outcome_key,
            "probability_percent": probability if outcome_key == "open" else None,
            "opportunity_count": len(stage_rows),
            "unpriced_opportunity_count": stage_unpriced,
            "unknown_probability_opportunity_count": stage_unknown,
            "gross_amount_by_currency": gross,
            "weighted_expected_amount_by_currency": weighted,
        })

    active_rows = [row for row in rows if stage_config.get(row.stage_key, {}).get("outcome_key", "open") == "open"]
    terminal_keys = {key for key, config in stage_config.items() if config.get("outcome_key") in ("won", "lost")}
    unscheduled_count = sum(row.stage_key not in terminal_keys for row in unscheduled_rows)
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
            "opportunity_count": len(active_rows), "closed_won_count": closed_won_count,
            "closed_lost_count": closed_lost_count, "unscheduled_opportunity_count": unscheduled_count,
            "organization_unit_id": str(organization_unit_id) if organization_unit_id else None,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return SalesForecast(
        pipeline_id=pipeline.id, organization_unit_id=organization_unit_id,
        period_start=period_start, period_end=period_end,
        opportunity_count=len(active_rows), closed_won_count=closed_won_count,
        closed_lost_count=closed_lost_count, priced_opportunity_count=priced_count,
        unpriced_opportunity_count=unpriced_count,
        unknown_probability_opportunity_count=unknown_probability_count,
        unscheduled_opportunity_count=unscheduled_count,
        gross_amount_by_currency=total_gross,
        weighted_expected_amount_by_currency=total_weighted,
        amount_without_probability_by_currency=total_unknown,
        stages=results,
    )


@router.get("/outcomes", response_model=SalesOutcomeReport,
            operation_id="getCRMRecordedSalesOutcomes")
async def get_sales_outcomes(
    period_start: date = Query(...),
    period_end: date = Query(...),
    pipeline_id: UUID | None = None,
    organization_unit_id: UUID | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SalesOutcomeReport:
    if period_start > period_end or (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Outcome period must be ordered and no longer than 366 days")
    scopes = crm_scope_ids(context, permission_key="crm.opportunity:view")
    if organization_unit_id is not None:
        await _require(context, "crm.opportunity:view", organization_unit_id)
        scopes = select(OrganizationUnit.id).where(
            OrganizationUnit.tenant_id == context.access.tenant_id,
            OrganizationUnit.id == organization_unit_id,
            OrganizationUnit.id.in_(scopes),
        )
    pipeline_filters = [
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.entity_kind == "opportunity",
    ]
    if pipeline_id is not None:
        pipeline_filters.append(CRMPipeline.id == pipeline_id)
    pipelines = (await context.session.scalars(
        select(CRMPipeline).where(*pipeline_filters)
    )).all()
    stage_outcomes: dict[tuple[UUID, str], tuple[str, str]] = {}
    for pipeline in pipelines:
        for stage in pipeline.stages:
            if not isinstance(stage, dict) or not isinstance(stage.get("key"), str):
                continue
            outcome = stage.get("outcome_key", "open")
            if outcome in ("won", "lost"):
                stage_outcomes[(pipeline.id, stage["key"])] = (
                    outcome, str(stage.get("name", stage["key"]))
                )

    start_at = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    end_at = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    event_filters = [
        AuditEvent.tenant_id == context.access.tenant_id,
        AuditEvent.target_type == "crm_opportunity",
        AuditEvent.action_key.in_(("crm_opportunity.created", "crm_opportunity.updated")),
        AuditEvent.organization_unit_id.in_(scopes),
        AuditEvent.occurred_at >= start_at,
        AuditEvent.occurred_at < end_at,
    ]
    if pipeline_id is not None:
        event_filters.append(AuditEvent.after_state["pipeline_id"].astext == str(pipeline_id))
    events = (await context.session.scalars(
        select(AuditEvent).where(*event_filters)
        .order_by(AuditEvent.occurred_at, AuditEvent.event_id)
    )).all()
    aggregates: dict[tuple[UUID, str, str], dict[str, Any]] = {}
    for event in events:
        before = event.before_state or {}
        after = event.after_state or {}
        try:
            event_pipeline_id = UUID(str(after.get("pipeline_id")))
        except (ValueError, TypeError):
            continue
        after_stage = after.get("stage_key")
        terminal = stage_outcomes.get((event_pipeline_id, after_stage))
        if terminal is None:
            continue
        before_terminal = stage_outcomes.get((event_pipeline_id, before.get("stage_key")))
        if before_terminal == terminal:
            continue
        outcome, stage_name = terminal
        key = (event_pipeline_id, outcome, after_stage)
        row = aggregates.setdefault(key, {
            "stage_name": stage_name, "count": 0, "priced": 0, "unpriced": 0, "amounts": {},
        })
        row["count"] += 1
        amount = after.get("amount")
        currency = after.get("currency")
        if amount is None or currency is None:
            row["unpriced"] += 1
            continue
        try:
            value = Decimal(str(amount))
        except Exception:
            row["unpriced"] += 1
            continue
        row["priced"] += 1
        row["amounts"][currency] = row["amounts"].get(currency, Decimal("0")) + value

    won_amounts: dict[str, Decimal] = {}
    lost_amounts: dict[str, Decimal] = {}
    won_count = lost_count = 0
    buckets = []
    for (bucket_pipeline_id, outcome, key), row in sorted(
        aggregates.items(), key=lambda item: (str(item[0][0]), item[0][1], item[0][2])
    ):
        count_name = "won" if outcome == "won" else "lost"
        if outcome == "won":
            won_count += row["count"]
            totals = won_amounts
        else:
            lost_count += row["count"]
            totals = lost_amounts
        for currency, amount in row["amounts"].items():
            totals[currency] = totals.get(currency, Decimal("0")) + amount
        buckets.append(SalesOutcomeBucket(
            pipeline_id=bucket_pipeline_id, outcome_key=outcome, stage_key=key,
            stage_name=row["stage_name"], outcome_count=row["count"],
            priced_outcome_count=row["priced"], unpriced_outcome_count=row["unpriced"],
            amount_by_currency=row["amounts"],
        ))

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity_outcomes.viewed",
        target_type="crm_opportunity_outcome_report",
        target_key=str(pipeline_id or "authorized-scope"),
        organization_unit_id=organization_unit_id, before_state=None,
        after_state={"period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
            "won_count": won_count, "lost_count": lost_count, "bucket_count": len(buckets)},
        correlation_id=None,
    ))
    await context.session.flush()
    return SalesOutcomeReport(
        period_start=period_start, period_end=period_end, pipeline_id=pipeline_id,
        organization_unit_id=organization_unit_id, won_count=won_count, lost_count=lost_count,
        won_amount_by_currency=won_amounts, lost_amount_by_currency=lost_amounts,
        buckets=buckets,
    )
