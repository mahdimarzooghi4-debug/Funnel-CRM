"""Commission plans and auditable, non-payment calculation snapshots."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.commission_calculations import aggregate_commission_events
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommissionCalculation,
    CRMCommissionCalculationRow,
    CRMCommissionPlan,
    CRMCommissionPlanVersion,
    CRMProductCommerceEvent,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/commission-plans", tags=["CRM commissions"])
SIX_PLACES = Decimal("0.000001")


class CommissionPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_unit_id: UUID
    seller_membership_id: UUID | None = None
    name: str = Field(min_length=1, max_length=160)
    rate_percent: Decimal = Field(gt=0, le=100, max_digits=7, decimal_places=4)


class CommissionCalculationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    period_end: date
    request_id: UUID | None = None


class CommissionPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    rate_percent: Decimal | None = Field(default=None, gt=0, le=100, max_digits=7, decimal_places=4)
    is_active: bool | None = None


async def _authorized(context: TenantSessionContext, action: str, org_id: UUID) -> None:
    if not await has_crm_permission(context, permission_key=action, organization_unit_id=org_id):
        raise HTTPException(status_code=403, detail="Commission action is not authorized")


def _plan_json(row: CRMCommissionPlan) -> dict:
    return {
        "id": row.id,
        "organization_unit_id": row.organization_unit_id,
        "seller_membership_id": row.seller_membership_id,
        "name": row.name,
        "rate_percent": row.rate_percent,
        "version": row.version,
        "is_active": row.is_active,
        "created_at": row.created_at,
    }


@router.post("", status_code=201, operation_id="createCRMCommissionPlan")
async def create_plan(payload: CommissionPlanCreate, context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    await _authorized(context, "crm.commission:manage", payload.organization_unit_id)
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Plan name cannot be blank")
    if payload.seller_membership_id is not None:
        membership = await context.session.scalar(select(WorkspaceMembership.id).where(
            WorkspaceMembership.tenant_id == context.access.tenant_id,
            WorkspaceMembership.id == payload.seller_membership_id,
        ))
        if membership is None:
            raise HTTPException(status_code=422, detail="Seller membership is outside this workspace")
    plan = CRMCommissionPlan(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        seller_membership_id=payload.seller_membership_id,
        name=payload.name.strip(), rate_percent=payload.rate_percent,
        is_active=True, created_by_membership_id=context.access.membership_id,
    )
    context.session.add(plan)
    context.session.add(CRMCommissionPlanVersion(
        tenant_id=context.access.tenant_id, plan_id=plan.id, version=1,
        seller_membership_id=plan.seller_membership_id, name=plan.name,
        rate_percent=plan.rate_percent, is_active=plan.is_active,
        changed_by_membership_id=context.access.membership_id,
    ))
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_commission.plan_created",
        target_type="crm_commission_plan", target_key=str(plan.id),
        organization_unit_id=plan.organization_unit_id, before_state=None,
        after_state={"name": plan.name, "seller_membership_id": str(plan.seller_membership_id) if plan.seller_membership_id else None,
                     "rate_percent": str(plan.rate_percent)},
        correlation_id=None,
    ))
    await context.session.flush()
    return _plan_json(plan)


@router.patch("/{plan_id}", operation_id="updateCRMCommissionPlan")
async def update_plan(
    plan_id: UUID,
    payload: CommissionPlanUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    plan = await context.session.scalar(select(CRMCommissionPlan).where(
        CRMCommissionPlan.tenant_id == context.access.tenant_id,
        CRMCommissionPlan.id == plan_id,
    ).with_for_update())
    if plan is None:
        raise HTTPException(status_code=404, detail="Commission plan not found")
    await _authorized(context, "crm.commission:manage", plan.organization_unit_id)
    if payload.expected_version != plan.version:
        raise HTTPException(status_code=409, detail="Commission plan version is stale")
    changes = {
        key: value
        for key, value in payload.model_dump(
            exclude_unset=True, exclude={"expected_version"}
        ).items()
        if value is not None
    }
    if not changes:
        raise HTTPException(status_code=422, detail="At least one plan field must change")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(status_code=422, detail="Plan name cannot be blank")
    before = {key: (str(getattr(plan, key)) if key == "rate_percent" else getattr(plan, key))
              for key in changes}
    for key, value in changes.items():
        setattr(plan, key, value)
    plan.version += 1
    context.session.add(CRMCommissionPlanVersion(
        tenant_id=context.access.tenant_id, plan_id=plan.id, version=plan.version,
        seller_membership_id=plan.seller_membership_id, name=plan.name,
        rate_percent=plan.rate_percent, is_active=plan.is_active,
        changed_by_membership_id=context.access.membership_id,
    ))
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_commission.plan_updated",
        target_type="crm_commission_plan", target_key=str(plan.id),
        organization_unit_id=plan.organization_unit_id, before_state=before,
        after_state={**{key: (str(getattr(plan, key)) if key == "rate_percent" else getattr(plan, key))
                        for key in changes}, "version": plan.version},
        correlation_id=None,
    ))
    await context.session.flush()
    return _plan_json(plan)


@router.get("/{plan_id}/versions", operation_id="listCRMCommissionPlanVersions")
async def list_plan_versions(
    plan_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    plan = await context.session.scalar(select(CRMCommissionPlan).where(
        CRMCommissionPlan.tenant_id == context.access.tenant_id,
        CRMCommissionPlan.id == plan_id,
    ))
    if plan is None:
        raise HTTPException(status_code=404, detail="Commission plan not found")
    await _authorized(context, "crm.commission:view", plan.organization_unit_id)
    versions = await context.session.scalars(select(CRMCommissionPlanVersion).where(
        CRMCommissionPlanVersion.tenant_id == context.access.tenant_id,
        CRMCommissionPlanVersion.plan_id == plan_id,
    ).order_by(CRMCommissionPlanVersion.version.desc()).limit(100))
    return {"items": [{
        "plan_id": item.plan_id, "version": item.version,
        "seller_membership_id": item.seller_membership_id,
        "name": item.name, "rate_percent": item.rate_percent,
        "is_active": item.is_active,
        "changed_by_membership_id": item.changed_by_membership_id,
        "created_at": item.created_at,
    } for item in versions]}


@router.get("", operation_id="listCRMCommissionPlans")
async def list_plans(context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    scopes = crm_scope_ids(context, permission_key="crm.commission:view")
    rows = await context.session.scalars(select(CRMCommissionPlan).where(
        CRMCommissionPlan.tenant_id == context.access.tenant_id,
        CRMCommissionPlan.organization_unit_id.in_(scopes),
    ).order_by(CRMCommissionPlan.created_at.desc()).limit(500))
    return {"items": [_plan_json(row) for row in rows]}


@router.post("/{plan_id}/calculations", status_code=201, operation_id="calculateCRMCommission")
async def calculate_commission(
    plan_id: UUID,
    payload: CommissionCalculationCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if payload.period_start > payload.period_end or (payload.period_end - payload.period_start).days > 365:
        raise HTTPException(status_code=422, detail="Calculation period must be ordered and no longer than 366 days")
    plan = await context.session.scalar(select(CRMCommissionPlan).where(
        CRMCommissionPlan.tenant_id == context.access.tenant_id,
        CRMCommissionPlan.id == plan_id,
    ).with_for_update())
    if plan is None:
        raise HTTPException(status_code=404, detail="Commission plan not found")
    await _authorized(context, "crm.commission:manage", plan.organization_unit_id)
    if payload.request_id is not None:
        existing = await context.session.scalar(select(CRMCommissionCalculation).where(
            CRMCommissionCalculation.tenant_id == context.access.tenant_id,
            CRMCommissionCalculation.plan_id == plan.id,
            CRMCommissionCalculation.request_id == payload.request_id,
        ))
        if existing is not None:
            if (existing.period_start != payload.period_start
                    or existing.period_end != payload.period_end):
                raise HTTPException(status_code=409, detail="Calculation request ID was already used with different inputs")
            stored_rows = await context.session.scalars(select(CRMCommissionCalculationRow).where(
                CRMCommissionCalculationRow.tenant_id == context.access.tenant_id,
                CRMCommissionCalculationRow.calculation_id == existing.id,
        ).order_by(CRMCommissionCalculationRow.seller_membership_id, CRMCommissionCalculationRow.currency))
            rows = list(stored_rows)
            return {
                "id": existing.id, "plan_id": existing.plan_id,
                "period_start": existing.period_start, "period_end": existing.period_end,
                "timezone": "UTC", "rate_percent": existing.rate_percent,
                "plan_version": existing.plan_version,
                "rows": [{
                    "seller_membership_id": row.seller_membership_id,
                    "unattributed": row.seller_membership_id is None,
                    "excluded_from_commission": row.seller_membership_id is None,
                    "currency": row.currency, "paid_amount": row.paid_amount,
                    "refunded_amount": row.refunded_amount, "net_amount": row.net_amount,
                    "rate_percent": existing.rate_percent,
                    "commission_amount": row.commission_amount,
                    "source_event_ids": row.source_event_ids,
                } for row in rows],
                "unattributed_events_excluded_from_commission": True,
                "status": "calculation_only",
                "money_transfer_or_payroll_instruction_created": False,
                "request_id": existing.request_id,
            }
    if not plan.is_active:
        raise HTTPException(status_code=404, detail="Active commission plan not found")
    start = datetime.combine(payload.period_start, time.min, tzinfo=timezone.utc)
    end = datetime.combine(payload.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    filters = [
        CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
        CRMProductCommerceEvent.organization_unit_id == plan.organization_unit_id,
        CRMProductCommerceEvent.occurred_at >= start,
        CRMProductCommerceEvent.occurred_at < end,
    ]
    events = list(await context.session.scalars(select(CRMProductCommerceEvent).where(*filters).order_by(
        CRMProductCommerceEvent.occurred_at, CRMProductCommerceEvent.id,
    )))
    groups = aggregate_commission_events(events, seller_membership_id=plan.seller_membership_id)
    calculation = CRMCommissionCalculation(
        id=uuid4(), tenant_id=context.access.tenant_id, plan_id=plan.id,
        period_start=payload.period_start, period_end=payload.period_end,
        rate_percent=plan.rate_percent, plan_version=plan.version,
        request_id=payload.request_id,
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(calculation)
    await context.session.flush()
    output_rows = []
    for (seller_id, currency), totals in sorted(groups.items(), key=lambda item: (str(item[0][0] or ""), item[0][1])):
        net = totals["paid"] - totals["refunded"]
        commission = Decimal("0.000000") if seller_id is None else (
            net * plan.rate_percent / Decimal("100")
        ).quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN)
        row = CRMCommissionCalculationRow(
            id=uuid4(), tenant_id=context.access.tenant_id, calculation_id=calculation.id,
            seller_membership_id=seller_id, currency=currency,
            paid_amount=totals["paid"].quantize(SIX_PLACES),
            refunded_amount=totals["refunded"].quantize(SIX_PLACES),
            net_amount=net.quantize(SIX_PLACES), commission_amount=commission,
            source_event_ids=totals["ids"],
        )
        context.session.add(row)
        output_rows.append({
            "seller_membership_id": seller_id, "unattributed": seller_id is None,
            "excluded_from_commission": seller_id is None,
            "currency": currency, "paid_amount": row.paid_amount,
            "refunded_amount": row.refunded_amount, "net_amount": row.net_amount,
            "rate_percent": plan.rate_percent, "commission_amount": row.commission_amount,
            "source_event_ids": row.source_event_ids,
        })
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_commission.calculation_created",
        target_type="crm_commission_calculation", target_key=str(calculation.id),
        organization_unit_id=plan.organization_unit_id, before_state=None,
        after_state={"plan_id": str(plan.id), "period_start": payload.period_start.isoformat(),
                     "period_end": payload.period_end.isoformat(), "row_count": len(output_rows),
                     "plan_version": plan.version,
                     "request_id": str(payload.request_id) if payload.request_id else None},
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "id": calculation.id, "plan_id": plan.id,
        "period_start": payload.period_start, "period_end": payload.period_end,
        "timezone": "UTC", "rate_percent": plan.rate_percent,
        "plan_version": plan.version,
        "request_id": payload.request_id,
        "rows": output_rows,
            "unattributed_events_excluded_from_commission": True,
        "status": "calculation_only",
        "money_transfer_or_payroll_instruction_created": False,
    }


@router.get("/{plan_id}/calculations", operation_id="listCRMCommissionCalculations")
async def list_calculations(plan_id: UUID, context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    plan = await context.session.scalar(select(CRMCommissionPlan).where(
        CRMCommissionPlan.tenant_id == context.access.tenant_id,
        CRMCommissionPlan.id == plan_id,
    ))
    if plan is None:
        raise HTTPException(status_code=404, detail="Commission plan not found")
    await _authorized(context, "crm.commission:view", plan.organization_unit_id)
    calculations = list(await context.session.scalars(select(CRMCommissionCalculation).where(
        CRMCommissionCalculation.tenant_id == context.access.tenant_id,
        CRMCommissionCalculation.plan_id == plan_id,
    ).order_by(CRMCommissionCalculation.created_at.desc()).limit(100)))
    items = []
    for calculation in calculations:
        rows = await context.session.scalars(select(CRMCommissionCalculationRow).where(
            CRMCommissionCalculationRow.tenant_id == context.access.tenant_id,
            CRMCommissionCalculationRow.calculation_id == calculation.id,
        ).order_by(CRMCommissionCalculationRow.currency, CRMCommissionCalculationRow.seller_membership_id))
        items.append({
            "id": calculation.id, "period_start": calculation.period_start,
            "period_end": calculation.period_end, "rate_percent": calculation.rate_percent,
            "plan_version": calculation.plan_version,
            "request_id": calculation.request_id,
            "created_at": calculation.created_at,
            "rows": [{"seller_membership_id": row.seller_membership_id,
                      "unattributed": row.seller_membership_id is None,
                      "excluded_from_commission": row.seller_membership_id is None,
                      "currency": row.currency, "paid_amount": row.paid_amount,
                      "refunded_amount": row.refunded_amount, "net_amount": row.net_amount,
                      "commission_amount": row.commission_amount,
                      "source_event_ids": row.source_event_ids} for row in rows],
        })
    return {"items": items}
