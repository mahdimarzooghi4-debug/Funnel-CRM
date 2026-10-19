"""Manager dashboard combining sales pipeline and follow-up work health."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMOpportunity,
    CRMPipeline,
    CRMWorkItem,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/analytics/sales-operations", tags=["CRM sales operations"])


class SalesStageSnapshot(BaseModel):
    stage_key: str
    stage_name: str
    probability_percent: int | None
    opportunity_count: int
    unpriced_opportunity_count: int
    amount_by_currency: dict[str, Decimal]


class OpportunityFollowUpCoverage(BaseModel):
    opportunity_count: int
    with_open_follow_up_count: int
    without_open_follow_up_count: int


class SalesWorkQueueHealth(BaseModel):
    status_counts: dict[str, int]
    active_count: int
    overdue_active_count: int
    unassigned_active_count: int
    due_in_next_seven_days_count: int
    active_by_priority: dict[str, int]


class SalesOperationsDashboard(BaseModel):
    organization_unit_id: UUID
    pipeline_id: UUID
    generated_at: datetime
    opportunities_by_stage: list[SalesStageSnapshot]
    follow_up_coverage: OpportunityFollowUpCoverage
    work_queue: SalesWorkQueueHealth


@router.get("", response_model=SalesOperationsDashboard,
            operation_id="getCRMSalesOperationsDashboard")
async def get_sales_operations_dashboard(
    organization_unit_id: UUID,
    pipeline_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SalesOperationsDashboard:
    for permission in ("crm.opportunity:view", "crm.work_item:view"):
        if not await has_crm_permission(
            context, permission_key=permission,
            organization_unit_id=organization_unit_id,
        ):
            raise HTTPException(status_code=403, detail="Sales operations dashboard is not authorized")
    pipeline = await context.session.scalar(select(CRMPipeline).where(
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.id == pipeline_id,
        CRMPipeline.entity_kind == "opportunity",
    ))
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Opportunity pipeline not found")

    base_opportunities = (
        CRMOpportunity.tenant_id == context.access.tenant_id,
        CRMOpportunity.organization_unit_id == organization_unit_id,
        CRMOpportunity.pipeline_id == pipeline.id,
    )
    aggregate_rows = (await context.session.execute(
        select(
            CRMOpportunity.stage_key,
            CRMOpportunity.currency,
            func.count(CRMOpportunity.id),
            func.sum(CRMOpportunity.amount),
        ).where(*base_opportunities).group_by(
            CRMOpportunity.stage_key, CRMOpportunity.currency
        )
    )).all()
    by_stage: dict[str, dict[str, Any]] = {}
    opportunity_count = 0
    for stage_key, currency, count, amount in aggregate_rows:
        item = by_stage.setdefault(stage_key, {
            "opportunity_count": 0,
            "unpriced_opportunity_count": 0,
            "amount_by_currency": {},
        })
        item["opportunity_count"] += count
        opportunity_count += count
        if currency is None:
            item["unpriced_opportunity_count"] += count
        else:
            item["amount_by_currency"][currency] = amount or Decimal("0")

    configured_stages = [
        stage for stage in pipeline.stages
        if isinstance(stage, dict) and isinstance(stage.get("key"), str)
    ]
    stage_snapshots = []
    seen = set()
    for stage in configured_stages:
        key = stage["key"]
        seen.add(key)
        probability = stage.get("probability_percent")
        if not isinstance(probability, int) or isinstance(probability, bool) or not 0 <= probability <= 100:
            probability = None
        values = by_stage.pop(key, {
            "opportunity_count": 0,
            "unpriced_opportunity_count": 0,
            "amount_by_currency": {},
        })
        stage_snapshots.append(SalesStageSnapshot(
            stage_key=key, stage_name=str(stage.get("name", key)),
            probability_percent=probability, **values,
        ))
    for key in sorted(by_stage):
        values = by_stage[key]
        stage_snapshots.append(SalesStageSnapshot(
            stage_key=key, stage_name=key, probability_percent=None, **values,
        ))

    active_statuses = ("open", "in_progress")
    active_work = (
        CRMWorkItem.tenant_id == context.access.tenant_id,
        CRMWorkItem.organization_unit_id == organization_unit_id,
        CRMWorkItem.status.in_(active_statuses),
    )
    status_rows = (await context.session.execute(
        select(CRMWorkItem.status, func.count(CRMWorkItem.id))
        .where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.organization_unit_id == organization_unit_id,
        )
        .group_by(CRMWorkItem.status)
    )).all()
    status_counts = {status: count for status, count in status_rows}
    active_count = sum(status_counts.get(status, 0) for status in active_statuses)
    now = datetime.now(timezone.utc)
    overdue_count = int(await context.session.scalar(
        select(func.count(CRMWorkItem.id)).where(
            *active_work, CRMWorkItem.due_at.is_not(None), CRMWorkItem.due_at < now,
        )
    ) or 0)
    unassigned_count = int(await context.session.scalar(
        select(func.count(CRMWorkItem.id)).where(
            *active_work, CRMWorkItem.assigned_membership_id.is_(None),
        )
    ) or 0)
    due_soon_count = int(await context.session.scalar(
        select(func.count(CRMWorkItem.id)).where(
            *active_work, CRMWorkItem.due_at >= now,
            CRMWorkItem.due_at <= now + timedelta(days=7),
        )
    ) or 0)
    priority_rows = (await context.session.execute(
        select(CRMWorkItem.priority, func.count(CRMWorkItem.id))
        .where(*active_work).group_by(CRMWorkItem.priority)
    )).all()
    active_by_priority = {priority: count for priority, count in priority_rows}

    active_follow_up_opportunities = select(CRMWorkItem.opportunity_id).where(
        CRMWorkItem.tenant_id == context.access.tenant_id,
        CRMWorkItem.organization_unit_id == organization_unit_id,
        CRMWorkItem.opportunity_id.is_not(None),
        CRMWorkItem.status.in_(active_statuses),
    )
    with_follow_up = int(await context.session.scalar(
        select(func.count(CRMOpportunity.id)).where(
            *base_opportunities,
            CRMOpportunity.id.in_(active_follow_up_opportunities),
        )
    ) or 0)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_sales_operations_dashboard.viewed",
        target_type="crm_sales_operations_dashboard",
        target_key=f"{organization_unit_id}:{pipeline.id}",
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "pipeline_id": str(pipeline.id),
            "opportunity_count": opportunity_count,
            "with_open_follow_up_count": with_follow_up,
            "active_work_item_count": active_count,
            "overdue_active_count": overdue_count,
            "unassigned_active_count": unassigned_count,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return SalesOperationsDashboard(
        organization_unit_id=organization_unit_id,
        pipeline_id=pipeline.id,
        generated_at=now,
        opportunities_by_stage=stage_snapshots,
        follow_up_coverage=OpportunityFollowUpCoverage(
            opportunity_count=opportunity_count,
            with_open_follow_up_count=with_follow_up,
            without_open_follow_up_count=opportunity_count - with_follow_up,
        ),
        work_queue=SalesWorkQueueHealth(
            status_counts=status_counts,
            active_count=active_count,
            overdue_active_count=overdue_count,
            unassigned_active_count=unassigned_count,
            due_in_next_seven_days_count=due_soon_count,
            active_by_priority=active_by_priority,
        ),
    )
