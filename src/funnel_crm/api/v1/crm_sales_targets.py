"""Team sales targets and attainment by pipeline period and currency."""

from datetime import date
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


@router.get("/performance", operation_id="getCRMSalesTargetPerformance")
async def sales_target_performance(
    organization_unit_id: UUID | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
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
    targets = list(await context.session.scalars(select(CRMSalesTarget).where(*filters).order_by(
        CRMSalesTarget.period_start, CRMSalesTarget.organization_unit_id,
        CRMSalesTarget.pipeline_id, CRMSalesTarget.currency,
    ).limit(500)))
    items = []
    for target in targets:
        pipeline = await context.session.get(CRMPipeline, target.pipeline_id)
        won_stage_keys = [
            stage.get("key") for stage in pipeline.stages
            if isinstance(stage, dict) and stage.get("outcome_key") == "won"
        ] if pipeline else []
        actual = Decimal("0")
        count = 0
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
            count = len(opportunities)
            actual = sum((row.amount or Decimal("0") for row in opportunities), Decimal("0"))
        item = _serialize(target)
        item.update({
            "actual_won_amount": actual,
            "won_opportunity_count": count,
            "attainment_percent": (actual / target.target_amount * Decimal("100")).quantize(Decimal("0.01")),
            "basis": "current_won_stage_and_expected_close_date",
        })
        items.append(item)
    return {"items": items, "currency_basis": "Each target is reported in its own currency; currencies are never combined."}
