"""Team sales targets and attainment by pipeline period and currency."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import CRMOpportunity, CRMPipeline, CRMSalesTarget, OrganizationUnit
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/sales-targets", tags=["CRM sales targets"])


class SalesTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_unit_id: UUID
    pipeline_id: UUID
    period_start: date
    period_end: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    target_amount: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


async def _authorized(context: TenantSessionContext, permission: str, org_id: UUID) -> None:
    if not await has_crm_permission(
        context, permission_key=permission, organization_unit_id=org_id
    ):
        raise HTTPException(status_code=403, detail="Sales target action is not authorized")


def _serialize(target: CRMSalesTarget) -> dict:
    return {
        "id": target.id,
        "organization_unit_id": target.organization_unit_id,
        "pipeline_id": target.pipeline_id,
        "period_start": target.period_start,
        "period_end": target.period_end,
        "currency": target.currency,
        "target_amount": target.target_amount,
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


@router.post("", status_code=201, operation_id="createCRMSalesTarget")
async def create_sales_target(
    payload: SalesTargetCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if payload.period_start > payload.period_end or (payload.period_end - payload.period_start).days > 365:
        raise HTTPException(status_code=422, detail="Target period must be ordered and no longer than 366 days")
    await _authorized(context, "crm.sales_target:manage", payload.organization_unit_id)
    pipeline = await context.session.scalar(select(CRMPipeline).where(
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.id == payload.pipeline_id,
        CRMPipeline.entity_kind == "opportunity",
    ))
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Opportunity pipeline not found")
    target = CRMSalesTarget(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        pipeline_id=pipeline.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        currency=payload.currency,
        target_amount=payload.target_amount,
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(target)
    await context.session.flush()
    return _serialize(target)


@router.get("", operation_id="listCRMSalesTargets")
async def list_sales_targets(
    organization_unit_id: UUID | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    pipeline_id: UUID | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if (period_start is None) != (period_end is None):
        raise HTTPException(status_code=422, detail="Provide both period boundaries")
    if period_start and (period_start > period_end or (period_end - period_start).days > 365):
        raise HTTPException(status_code=422, detail="Target period must be ordered and no longer than 366 days")
    scopes = crm_scope_ids(context, permission_key="crm.sales_target:view")
    filters = [
        CRMSalesTarget.tenant_id == context.access.tenant_id,
        CRMSalesTarget.organization_unit_id.in_(scopes),
    ]
    if organization_unit_id is not None:
        await _authorized(context, "crm.sales_target:view", organization_unit_id)
        filters.append(CRMSalesTarget.organization_unit_id == organization_unit_id)
    if period_start is not None:
        filters.extend([
            CRMSalesTarget.period_start >= period_start,
            CRMSalesTarget.period_end <= period_end,
        ])
    if pipeline_id is not None:
        filters.append(CRMSalesTarget.pipeline_id == pipeline_id)
    rows = await context.session.scalars(select(CRMSalesTarget).where(*filters).order_by(
        CRMSalesTarget.period_start, CRMSalesTarget.organization_unit_id,
        CRMSalesTarget.pipeline_id, CRMSalesTarget.currency,
    ).limit(500))
    return {"items": [_serialize(row) for row in rows]}


class SalesTargetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date | None = None
    period_end: date | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=6)


@router.patch("/{target_id}", operation_id="updateCRMSalesTarget")
async def update_sales_target(
    target_id: UUID,
    payload: SalesTargetUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if not payload.model_fields_set:
        raise HTTPException(status_code=422, detail="Provide at least one target field")
    if any(getattr(payload, field) is None for field in payload.model_fields_set):
        raise HTTPException(status_code=422, detail="Sales target fields cannot be null")
    target = await context.session.scalar(select(CRMSalesTarget).where(
        CRMSalesTarget.tenant_id == context.access.tenant_id,
        CRMSalesTarget.id == target_id,
    ).with_for_update())
    if target is None:
        raise HTTPException(status_code=404, detail="Sales target not found")
    await _authorized(context, "crm.sales_target:manage", target.organization_unit_id)
    start = payload.period_start if "period_start" in payload.model_fields_set else target.period_start
    end = payload.period_end if "period_end" in payload.model_fields_set else target.period_end
    if start is None or end is None or start > end or (end - start).days > 365:
        raise HTTPException(status_code=422, detail="Target period must be ordered and no longer than 366 days")
    if "period_start" in payload.model_fields_set:
        target.period_start = start
    if "period_end" in payload.model_fields_set:
        target.period_end = end
    if "currency" in payload.model_fields_set:
        target.currency = payload.currency
    if "target_amount" in payload.model_fields_set:
        target.target_amount = payload.target_amount
    target.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    return _serialize(target)


@router.get("/performance", operation_id="getCRMSalesTargetPerformance")
async def sales_target_performance(
    organization_unit_id: UUID | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    as_of_date: date | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if (period_start is None) != (period_end is None):
        raise HTTPException(status_code=422, detail="Provide both period boundaries")
    if period_start and (period_start > period_end or (period_end - period_start).days > 365):
        raise HTTPException(status_code=422, detail="Target period must be ordered and no longer than 366 days")
    as_of = as_of_date or datetime.now(timezone.utc).date()
    scopes = crm_scope_ids(context, permission_key="crm.sales_target:view")
    filters = [
        CRMSalesTarget.tenant_id == context.access.tenant_id,
        CRMSalesTarget.organization_unit_id.in_(scopes),
    ]
    if organization_unit_id is not None:
        await _authorized(context, "crm.sales_target:view", organization_unit_id)
        filters.append(CRMSalesTarget.organization_unit_id == organization_unit_id)
    if period_start is not None:
        filters.extend([
            CRMSalesTarget.period_start >= period_start,
            CRMSalesTarget.period_end <= period_end,
        ])
    targets = list(await context.session.scalars(select(CRMSalesTarget).where(*filters).order_by(
        CRMSalesTarget.period_start, CRMSalesTarget.organization_unit_id,
        CRMSalesTarget.pipeline_id, CRMSalesTarget.currency,
    ).limit(500)))
    items = []
    for target in targets:
        pipeline = await context.session.scalar(select(CRMPipeline).where(
            CRMPipeline.tenant_id == target.tenant_id,
            CRMPipeline.id == target.pipeline_id,
        ))
        won_stage_keys = [
            stage.get("key") for stage in pipeline.stages
            if isinstance(stage, dict) and stage.get("outcome_key") == "won"
        ] if pipeline else []
        opportunities = []
        if won_stage_keys:
            opportunities = list(await context.session.scalars(select(CRMOpportunity).where(
                CRMOpportunity.tenant_id == target.tenant_id,
                CRMOpportunity.organization_unit_id == target.organization_unit_id,
                CRMOpportunity.pipeline_id == target.pipeline_id,
                CRMOpportunity.stage_key.in_(won_stage_keys),
                CRMOpportunity.currency == target.currency,
                CRMOpportunity.expected_close_date >= target.period_start,
                CRMOpportunity.expected_close_date <= target.period_end,
            )))
        actual_total = sum((row.amount or Decimal("0") for row in opportunities), Decimal("0"))
        elapsed_end = min(max(as_of, target.period_start), target.period_end)
        elapsed_days = max((elapsed_end - target.period_start).days + (1 if as_of >= target.period_start else 0), 0)
        period_days = (target.period_end - target.period_start).days + 1
        expected_to_date = target.target_amount * Decimal(elapsed_days) / Decimal(period_days)
        actual_to_date = sum(
            (row.amount or Decimal("0") for row in opportunities
             if row.expected_close_date is not None and row.expected_close_date <= as_of),
            Decimal("0"),
        )
        if as_of < target.period_start:
            pace_status = "not_started"
        elif as_of >= target.period_end:
            pace_status = "achieved" if actual_total >= target.target_amount else "missed"
        else:
            pace_status = "ahead" if actual_to_date >= expected_to_date else "behind"
        monthly = {}
        for row in opportunities:
            if row.expected_close_date is not None:
                month_key = row.expected_close_date.strftime("%Y-%m")
                monthly[month_key] = monthly.get(month_key, Decimal("0")) + (row.amount or Decimal("0"))
        trend = []
        month_cursor = target.period_start.replace(day=1)
        cumulative_actual = Decimal("0")
        while month_cursor <= target.period_end:
            next_month = date(month_cursor.year + (1 if month_cursor.month == 12 else 0),
                              1 if month_cursor.month == 12 else month_cursor.month + 1, 1)
            bucket_end = min(next_month.fromordinal(next_month.toordinal() - 1), target.period_end)
            bucket_start = max(month_cursor, target.period_start)
            cumulative_actual += monthly.get(month_cursor.strftime("%Y-%m"), Decimal("0"))
            days_elapsed = (bucket_end - target.period_start).days + 1
            trend.append({
                "period_start": bucket_start,
                "period_end": bucket_end,
                "won_amount": monthly.get(month_cursor.strftime("%Y-%m"), Decimal("0")),
                "target_to_date": (target.target_amount * Decimal(days_elapsed) / Decimal(period_days)).quantize(Decimal("0.01")),
                "actual_to_date": cumulative_actual,
            })
            month_cursor = next_month
        item = _serialize(target)
        item.update({
            "actual_won_amount": actual_total,
            "won_to_date_amount": actual_to_date,
            "target_to_date_amount": expected_to_date.quantize(Decimal("0.01")),
            "pace_variance_amount": (actual_to_date - expected_to_date).quantize(Decimal("0.01")),
            "pace_status": pace_status,
            "won_opportunity_count": len(opportunities),
            "attainment_percent": (actual_total / target.target_amount * Decimal("100")).quantize(Decimal("0.01")),
            "basis": "current_won_stage_and_expected_close_date",
            "trend": trend,
        })
        items.append(item)
    return {
        "items": items,
        "as_of_date": as_of,
        "pacing_method": "linear_proration_by_calendar_day",
        "currency_basis": "Each target is reported in its own currency; currencies are never combined.",
    }
