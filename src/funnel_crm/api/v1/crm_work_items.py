"""Assignable, scoped work queue for customer and marketing follow-up."""

from datetime import datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import cast, func, select, String
from sqlalchemy.orm import aliased

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_campaign_targets import evaluate_net_paid_to_spend_target, evaluate_plan_metrics
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMProductCommerceEvent,
    CRMOpportunity,
    CRMPipeline,
    CRMSalesTarget,
    CRMProfile,
    CRMWorkItem,
    CRMWorkItemOutcome,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/work-items", tags=["CRM work queue"])
WorkItemStatus = Literal["open", "in_progress", "completed", "cancelled"]
WorkItemPriority = Literal["low", "normal", "high", "urgent"]
FollowUpOutcomeCode = Literal[
    "contact_made", "no_contact", "callback_requested", "not_interested", "other"
]
ActivityChannel = Literal["online", "phone", "store", "field", "support", "campaign", "other"]


class CampaignSignalWorkItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    target_plan_id: UUID
    metric_key: str = Field(min_length=1, max_length=80)
    assigned_membership_id: UUID | None = None
    due_at: datetime | None = None
    priority: WorkItemPriority = "high"
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("due_at")
    @classmethod
    def require_due_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a timezone")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class WorkItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    profile_id: UUID | None = None
    opportunity_id: UUID | None = None
    campaign_id: UUID | None = None
    assigned_membership_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None
    priority: WorkItemPriority = "normal"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must contain a non-whitespace character")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @model_validator(mode="after")
    def require_context(self):
        if self.profile_id is None and self.opportunity_id is None and self.campaign_id is None:
            raise ValueError("a work item must be linked to a customer, opportunity, or campaign")
        return self


class WorkItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: UUID | None = None
    opportunity_id: UUID | None = None
    campaign_id: UUID | None = None
    assigned_membership_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None
    priority: WorkItemPriority | None = None
    status: WorkItemStatus | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("title must contain a non-whitespace character")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for key in ("title", "priority", "status"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class WorkItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    profile_id: UUID | None
    opportunity_id: UUID | None
    campaign_id: UUID | None
    assigned_membership_id: UUID | None
    created_by_membership_id: UUID
    source_learning_review_id: UUID | None
    title: str
    description: str | None
    due_at: datetime | None
    priority: WorkItemPriority
    status: WorkItemStatus
    completed_at: datetime | None
    source_outcome_id: UUID | None
    source_campaign_target_plan_id: UUID | None
    source_campaign_metric_key: str | None
    source_campaign_signal_type: str | None
    created_at: datetime
    updated_at: datetime


class WorkItemOutcomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    outcome_code: FollowUpOutcomeCode
    channel: ActivityChannel
    notes: str | None = Field(default=None, max_length=2000)
    occurred_at: datetime | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class WorkItemOutcomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    organization_unit_id: UUID
    work_item_id: UUID
    profile_id: UUID
    recorded_by_membership_id: UUID
    outcome_code: FollowUpOutcomeCode
    channel: ActivityChannel
    notes: str | None
    occurred_at: datetime
    created_at: datetime


class OutcomeFollowUpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_membership_id: UUID | None = None
    due_at: datetime | None = None
    priority: WorkItemPriority = "normal"

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value


class OutcomeFollowUpBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    outcome_ids: list[UUID] = Field(min_length=1, max_length=100)
    assigned_membership_id: UUID | None = None
    due_at: datetime | None = None
    priority: WorkItemPriority = "normal"

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value


async def _require_permission(
    context: TenantSessionContext, permission_key: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="CRM work item action is not authorized for this organization scope")


async def _validate_context(
    context: TenantSessionContext,
    *,
    organization_unit_id: UUID,
    profile_id: UUID | None,
    opportunity_id: UUID | None,
    campaign_id: UUID | None,
) -> None:
    tenant_id = context.access.tenant_id
    if profile_id is None and opportunity_id is None and campaign_id is None:
        raise HTTPException(status_code=422, detail="A work item must retain a linked customer, opportunity, or campaign")
    profile = None
    if profile_id is not None:
        profile = await context.session.scalar(
            select(CRMProfile).where(
                CRMProfile.tenant_id == tenant_id,
                CRMProfile.organization_unit_id == organization_unit_id,
                CRMProfile.id == profile_id,
                CRMProfile.archived_at.is_(None),
                CRMProfile.merged_into_profile_id.is_(None),
            )
        )
        if profile is None:
            raise HTTPException(status_code=422, detail="Customer must be active in the selected organization")
    opportunity = None
    if opportunity_id is not None:
        opportunity = await context.session.scalar(
            select(CRMOpportunity).where(
                CRMOpportunity.tenant_id == tenant_id,
                CRMOpportunity.organization_unit_id == organization_unit_id,
                CRMOpportunity.id == opportunity_id,
            )
        )
        if opportunity is None:
            raise HTTPException(status_code=422, detail="Opportunity must belong to the selected organization")
    if campaign_id is not None:
        campaign = await context.session.scalar(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.organization_unit_id == organization_unit_id,
                CRMMarketingCampaign.id == campaign_id,
            )
        )
        if campaign is None:
            raise HTTPException(status_code=422, detail="Campaign must belong to the selected organization")
    if profile is not None and opportunity is not None and opportunity.profile_id not in (None, profile.id):
        raise HTTPException(status_code=422, detail="Customer and opportunity references do not match")


async def _validate_assignee(context: TenantSessionContext, member_id: UUID | None) -> None:
    if member_id is None:
        return
    member = await context.session.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.tenant_id == context.access.tenant_id,
            WorkspaceMembership.id == member_id,
            WorkspaceMembership.status == "active",
        )
    )
    if member is None:
        raise HTTPException(status_code=422, detail="Assignee must be an active member of this workspace")


def _snapshot(item: CRMWorkItem) -> dict:
    return {
        "organization_unit_id": str(item.organization_unit_id),
        "profile_id": str(item.profile_id) if item.profile_id else None,
        "opportunity_id": str(item.opportunity_id) if item.opportunity_id else None,
        "campaign_id": str(item.campaign_id) if item.campaign_id else None,
        "source_learning_review_id": str(item.source_learning_review_id) if item.source_learning_review_id else None,
        "source_outcome_id": str(item.source_outcome_id) if item.source_outcome_id else None,
        "source_campaign_target_plan_id": str(item.source_campaign_target_plan_id) if item.source_campaign_target_plan_id else None,
        "source_campaign_metric_key": item.source_campaign_metric_key,
        "source_campaign_signal_type": item.source_campaign_signal_type,
        "assigned_membership_id": str(item.assigned_membership_id) if item.assigned_membership_id else None,
        "title": item.title,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "priority": item.priority,
        "status": item.status,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _audit(
    context: TenantSessionContext,
    item: CRMWorkItem,
    action_key: str,
    before: dict | None,
    after: dict,
) -> None:
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key=action_key,
        target_type="crm_work_item",
        target_key=str(item.id),
        organization_unit_id=item.organization_unit_id,
        before_state=before,
        after_state=after,
        correlation_id=None,
    ))


@router.post("", response_model=WorkItemRead, status_code=201,
             operation_id="createCRMWorkItem")
async def create_work_item(
    payload: WorkItemCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> WorkItemRead:
    await _require_permission(context, "crm.work_item:create", payload.organization_unit_id)
    await _validate_context(
        context, organization_unit_id=payload.organization_unit_id,
        profile_id=payload.profile_id, opportunity_id=payload.opportunity_id,
        campaign_id=payload.campaign_id,
    )
    await _validate_assignee(context, payload.assigned_membership_id)
    item = CRMWorkItem(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        profile_id=payload.profile_id, opportunity_id=payload.opportunity_id,
        campaign_id=payload.campaign_id, assigned_membership_id=payload.assigned_membership_id,
        created_by_membership_id=context.access.membership_id,
        title=payload.title, description=payload.description, due_at=payload.due_at,
        priority=payload.priority, status="open", completed_at=None,
    )
    context.session.add(item)
    await context.session.flush()
    _audit(context, item, "crm_work_item.created", None, _snapshot(item))
    await context.session.flush()
    return WorkItemRead.model_validate(item)



@router.post(
    "/from-campaign-signal",
    response_model=WorkItemRead,
    status_code=201,
    operation_id="createCRMWorkItemFromCampaignSignal",
)
async def create_work_item_from_campaign_signal(
    payload: CampaignSignalWorkItemCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> WorkItemRead:
    plan = await context.session.scalar(
        select(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.campaign_id == payload.campaign_id,
            CRMMarketingCampaignTargetPlan.id == payload.target_plan_id,
        ).with_for_update()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Campaign target plan not found")
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == payload.campaign_id,
            CRMMarketingCampaign.organization_unit_id == plan.organization_unit_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="CRM campaign not found")
    await _require_permission(context, "crm.campaign:view", campaign.organization_unit_id)
    await _require_permission(context, "crm.work_item:create", campaign.organization_unit_id)
    await _validate_assignee(context, payload.assigned_membership_id)

    measurements = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign.id,
            CRMMarketingCampaignMeasurement.measured_on >= plan.period_start,
            CRMMarketingCampaignMeasurement.measured_on <= plan.period_end,
        ).order_by(CRMMarketingCampaignMeasurement.measured_on)
    )).all()
    if payload.metric_key == "period_net_paid_to_spend":
        await _require_permission(context, "crm.commerce_event:view", campaign.organization_unit_id)
        events = (await context.session.scalars(
            select(CRMProductCommerceEvent).where(
                CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                CRMProductCommerceEvent.organization_unit_id == campaign.organization_unit_id,
                CRMProductCommerceEvent.campaign_id == campaign.id,
                CRMProductCommerceEvent.occurred_at >= datetime.combine(plan.period_start, time.min, tzinfo=timezone.utc),
                CRMProductCommerceEvent.occurred_at < datetime.combine(plan.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc),
            ).order_by(CRMProductCommerceEvent.occurred_at)
        )).all()
        metric = evaluate_net_paid_to_spend_target(plan, list(measurements), list(events))
    else:
        metric = evaluate_plan_metrics(plan, list(measurements)).get(payload.metric_key)
    if metric is None:
        raise HTTPException(status_code=422, detail="Metric is not part of this campaign target plan")
    has_signal = metric.observed_days < metric.period_days or metric.status == "not_met"
    if not has_signal:
        raise HTTPException(status_code=409, detail="The selected metric has no current follow-up signal")
    existing = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.campaign_id == campaign.id,
            CRMWorkItem.source_campaign_target_plan_id == plan.id,
            CRMWorkItem.source_campaign_metric_key == payload.metric_key,
            CRMWorkItem.status.in_(["open", "in_progress"]),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"message": "An open follow-up already exists for this campaign signal", "work_item_id": str(existing.id)},
        )

    signal_kind = "measurement_gap" if metric.observed_days < metric.period_days else "target_gap"
    metric_label = payload.metric_key.replace("_", " ")
    title = f"Review {campaign.name}: {metric_label}"[:200]
    evidence = (
        f"Campaign performance signal ({signal_kind}). "
        f"Actual: {metric.actual if metric.actual is not None else 'no data'}; "
        f"target: {metric.target}; coverage: {metric.observed_days}/{metric.period_days} days."
    )
    description = evidence + (f"\\nManager note: {payload.note}" if payload.note else "")
    item = CRMWorkItem(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=campaign.organization_unit_id,
        profile_id=None, opportunity_id=None, campaign_id=campaign.id,
        assigned_membership_id=payload.assigned_membership_id,
        created_by_membership_id=context.access.membership_id,
        title=title, description=description[:2000], due_at=payload.due_at,
        priority=payload.priority, status="open", completed_at=None,
        source_campaign_target_plan_id=plan.id,
        source_campaign_metric_key=payload.metric_key,
        source_campaign_signal_type=signal_kind,
    )
    context.session.add(item)
    await context.session.flush()
    after = _snapshot(item)
    after["source_campaign_signal"] = {
        "target_plan_id": str(plan.id),
        "metric_key": payload.metric_key,
        "signal_type": signal_kind,
        "actual": str(metric.actual) if metric.actual is not None else None,
        "target": str(metric.target),
        "observed_days": metric.observed_days,
        "period_days": metric.period_days,
    }
    _audit(context, item, "crm_work_item.created_from_campaign_signal", None, after)
    await context.session.flush()
    return WorkItemRead.model_validate(item)


@router.get("", response_model=list[WorkItemRead],
            operation_id="listCRMWorkItems")
async def list_work_items(
    organization_unit_id: UUID,
    status: WorkItemStatus | None = Query(default=None),
    assigned_to_me: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[WorkItemRead]:
    await _require_permission(context, "crm.work_item:view", organization_unit_id)
    stmt = select(CRMWorkItem).where(
        CRMWorkItem.tenant_id == context.access.tenant_id,
        CRMWorkItem.organization_unit_id == organization_unit_id,
    )
    if status is not None:
        stmt = stmt.where(CRMWorkItem.status == status)
    if assigned_to_me:
        stmt = stmt.where(CRMWorkItem.assigned_membership_id == context.access.membership_id)
    items = (await context.session.scalars(
        stmt.order_by(CRMWorkItem.due_at.asc().nulls_last(), CRMWorkItem.created_at.desc()).limit(limit)
    )).all()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.listed",
        target_type="crm_work_item_collection",
        target_key=str(organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={"status": status, "assigned_to_me": assigned_to_me, "result_count": len(items)},
        correlation_id=None,
    ))
    await context.session.flush()
    return [WorkItemRead.model_validate(item) for item in items]


@router.get(
    "/lifecycle-review-readout",
    response_model=dict,
    operation_id="getCRMLifecycleReviewReadout",
)
async def get_lifecycle_review_readout(
    organization_unit_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    """Summarize task completion and later recorded activity for review-created work."""
    tenant_id = context.access.tenant_id
    await _require_permission(context, "crm.work_item:view", organization_unit_id)
    is_review_item = select(AuditEvent.event_id).where(
        AuditEvent.tenant_id == tenant_id,
        AuditEvent.target_type == "crm_work_item",
        AuditEvent.target_key == cast(CRMWorkItem.id, String),
        AuditEvent.action_key == "crm_work_item.created_from_lifecycle_review",
    ).exists()
    filters = (
        CRMWorkItem.tenant_id == tenant_id,
        CRMWorkItem.organization_unit_id == organization_unit_id,
        is_review_item,
    )
    status_rows = (await context.session.execute(
        select(CRMWorkItem.status, func.count(CRMWorkItem.id))
        .where(*filters)
        .group_by(CRMWorkItem.status)
    )).all()
    status_counts = {status: count for status, count in status_rows}
    activity_count, profile_count = (await context.session.execute(
        select(
            func.count(func.distinct(CRMCustomerActivity.id)),
            func.count(func.distinct(CRMCustomerActivity.profile_id)),
        )
        .select_from(CRMWorkItem)
        .join(
            CRMCustomerActivity,
            (CRMCustomerActivity.tenant_id == tenant_id)
            & (CRMCustomerActivity.profile_id == CRMWorkItem.profile_id)
            & (CRMCustomerActivity.occurred_at >= CRMWorkItem.created_at),
        )
        .where(*filters, CRMWorkItem.profile_id.is_not(None))
    )).one()
    outcome_rows = (await context.session.execute(
        select(CRMWorkItemOutcome.outcome_code, func.count(CRMWorkItemOutcome.id))
        .select_from(CRMWorkItemOutcome)
        .join(
            CRMWorkItem,
            (CRMWorkItem.tenant_id == CRMWorkItemOutcome.tenant_id)
            & (CRMWorkItem.id == CRMWorkItemOutcome.work_item_id),
        )
        .where(*filters)
        .group_by(CRMWorkItemOutcome.outcome_code)
    )).all()
    outcome_counts = {code: count for code, count in outcome_rows}
    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.lifecycle_review_readout_viewed",
        target_type="crm_work_item_collection",
        target_key=str(organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "review_item_count": sum(status_counts.values()),
            "recorded_activities_after_task_count": activity_count,
            "profiles_with_recorded_activity_after_task_count": profile_count,
            "follow_up_outcome_count_by_code": outcome_counts,
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "review_item_count": sum(status_counts.values()),
        "work_item_count_by_status": {
            status: status_counts.get(status, 0)
            for status in ("open", "in_progress", "completed", "cancelled")
        },
        "recorded_activities_after_task_count": activity_count,
        "profiles_with_recorded_activity_after_task_count": profile_count,
        "follow_up_outcome_count_by_code": {
            code: outcome_counts.get(code, 0)
            for code in ("contact_made", "no_contact", "callback_requested", "not_interested", "other")
        },
        "interpretation": (
            "Later recorded activity is descriptive timing evidence only; it does not establish "
            "that a work item caused the activity or a customer outcome."
        ),
    }


@router.get(
    "/lifecycle-review-performance",
    response_model=dict,
    operation_id="getCRMLifecycleReviewPerformance",
)
async def get_lifecycle_review_performance(
    organization_unit_id: UUID,
    start_at: datetime,
    end_at: datetime,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    """Report explicit follow-up outcomes by recorder, channel, and outcome code."""
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="start_at and end_at must include timezones")
    if start_at >= end_at:
        raise HTTPException(status_code=422, detail="start_at must be earlier than end_at")

    tenant_id = context.access.tenant_id
    await _require_permission(context, "crm.work_item:view", organization_unit_id)
    lifecycle_item = select(AuditEvent.event_id).where(
        AuditEvent.tenant_id == tenant_id,
        AuditEvent.target_type == "crm_work_item",
        AuditEvent.target_key == cast(CRMWorkItem.id, String),
        AuditEvent.action_key == "crm_work_item.created_from_lifecycle_review",
    ).exists()
    filters = (
        CRMWorkItemOutcome.tenant_id == tenant_id,
        CRMWorkItemOutcome.organization_unit_id == organization_unit_id,
        CRMWorkItemOutcome.occurred_at >= start_at,
        CRMWorkItemOutcome.occurred_at < end_at,
        CRMWorkItem.tenant_id == tenant_id,
        CRMWorkItem.organization_unit_id == organization_unit_id,
        lifecycle_item,
    )
    total_outcomes, work_item_count, profile_count = (await context.session.execute(
        select(
            func.count(CRMWorkItemOutcome.id),
            func.count(func.distinct(CRMWorkItemOutcome.work_item_id)),
            func.count(func.distinct(CRMWorkItemOutcome.profile_id)),
        )
        .select_from(CRMWorkItemOutcome)
        .join(
            CRMWorkItem,
            (CRMWorkItem.tenant_id == CRMWorkItemOutcome.tenant_id)
            & (CRMWorkItem.id == CRMWorkItemOutcome.work_item_id),
        )
        .where(*filters)
    )).one()
    rows = (await context.session.execute(
        select(
            CRMWorkItemOutcome.recorded_by_membership_id,
            CRMWorkItemOutcome.channel,
            CRMWorkItemOutcome.outcome_code,
            func.count(CRMWorkItemOutcome.id).label("outcome_count"),
            func.count(func.distinct(CRMWorkItemOutcome.work_item_id)).label("work_item_count"),
            func.count(func.distinct(CRMWorkItemOutcome.profile_id)).label("profile_count"),
        )
        .select_from(CRMWorkItemOutcome)
        .join(
            CRMWorkItem,
            (CRMWorkItem.tenant_id == CRMWorkItemOutcome.tenant_id)
            & (CRMWorkItem.id == CRMWorkItemOutcome.work_item_id),
        )
        .where(*filters)
        .group_by(
            CRMWorkItemOutcome.recorded_by_membership_id,
            CRMWorkItemOutcome.channel,
            CRMWorkItemOutcome.outcome_code,
        )
        .order_by(
            CRMWorkItemOutcome.recorded_by_membership_id,
            CRMWorkItemOutcome.channel,
            CRMWorkItemOutcome.outcome_code,
        )
    )).all()
    breakdown = [
        {
            "recorded_by_membership_id": str(row.recorded_by_membership_id),
            "channel": row.channel,
            "outcome_code": row.outcome_code,
            "outcome_count": row.outcome_count,
            "work_item_count": row.work_item_count,
            "profile_count": row.profile_count,
        }
        for row in rows
    ]
    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.lifecycle_review_performance_viewed",
        target_type="crm_work_item_collection",
        target_key=str(organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "outcome_count": total_outcomes,
            "breakdown_count": len(breakdown),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {
        "organization_unit_id": str(organization_unit_id),
        "window": {
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "end_at_is_exclusive": True,
        },
        "totals": {
            "outcome_count": total_outcomes,
            "work_item_count": work_item_count,
            "profile_count": profile_count,
        },
        "breakdown": breakdown,
        "interpretation": (
            "These are human-recorded follow-up outcomes by time, recorder, and channel. "
            "They do not establish causal effectiveness or customer sentiment."
        ),
    }


@router.post(
    "/outcomes/{outcome_id}/follow-up",
    response_model=WorkItemRead,
    status_code=201,
    operation_id="createCRMFollowUpFromOutcome",
)
async def create_follow_up_from_outcome(
    outcome_id: UUID,
    payload: OutcomeFollowUpCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> WorkItemRead:
    """Let an authorized manager explicitly turn a callback/no-contact outcome into a task."""
    tenant_id = context.access.tenant_id
    outcome = await context.session.scalar(
        select(CRMWorkItemOutcome).where(
            CRMWorkItemOutcome.tenant_id == tenant_id,
            CRMWorkItemOutcome.id == outcome_id,
        ).with_for_update()
    )
    if outcome is None:
        raise HTTPException(status_code=404, detail="Follow-up outcome not found")
    await _require_permission(context, "crm.work_item:create", outcome.organization_unit_id)
    if outcome.outcome_code not in ("callback_requested", "no_contact"):
        raise HTTPException(status_code=409, detail="This outcome does not request another follow-up")

    existing = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == tenant_id,
            CRMWorkItem.source_outcome_id == outcome.id,
        )
    )
    if existing is not None:
        return WorkItemRead.model_validate(existing)

    profile = await context.session.scalar(
        select(CRMProfile).where(
            CRMProfile.tenant_id == tenant_id,
            CRMProfile.organization_unit_id == outcome.organization_unit_id,
            CRMProfile.id == outcome.profile_id,
            CRMProfile.archived_at.is_(None),
            CRMProfile.merged_into_profile_id.is_(None),
        )
    )
    if profile is None:
        raise HTTPException(status_code=409, detail="Customer is no longer active for follow-up")
    await _validate_assignee(context, payload.assigned_membership_id)
    reason = "callback requested" if outcome.outcome_code == "callback_requested" else "no contact"
    item = CRMWorkItem(
        id=uuid4(), tenant_id=tenant_id,
        organization_unit_id=outcome.organization_unit_id,
        profile_id=outcome.profile_id,
        opportunity_id=None, campaign_id=None,
        assigned_membership_id=payload.assigned_membership_id,
        created_by_membership_id=context.access.membership_id,
        title=f"Lifecycle follow-up: {reason}",
        description=f"Created from recorded outcome {outcome.id}; review the outcome before contacting the customer.",
        due_at=payload.due_at, priority=payload.priority,
        status="open", completed_at=None,
        source_outcome_id=outcome.id,
    )
    context.session.add(item)
    await context.session.flush()
    _audit(context, item, "crm_work_item.created", None, _snapshot(item))
    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.created_from_outcome",
        target_type="crm_work_item_outcome",
        target_key=str(outcome.id),
        organization_unit_id=outcome.organization_unit_id,
        before_state=None,
        after_state={"work_item_id": str(item.id), "outcome_code": outcome.outcome_code},
        correlation_id=None,
    ))
    await context.session.flush()
    return WorkItemRead.model_validate(item)


@router.post(
    "/outcomes/follow-up-batch",
    response_model=dict,
    status_code=201,
    operation_id="createCRMLifecycleFollowUpBatch",
)
async def create_lifecycle_follow_up_batch(
    payload: OutcomeFollowUpBatchCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    """Create selected follow-up tasks together or reject the entire selection."""
    if len(set(payload.outcome_ids)) != len(payload.outcome_ids):
        raise HTTPException(status_code=422, detail="Outcome IDs must be unique")
    tenant_id = context.access.tenant_id
    organization_unit_id = payload.organization_unit_id
    await _require_permission(context, "crm.work_item:create", organization_unit_id)
    await _validate_assignee(context, payload.assigned_membership_id)
    outcomes = list(await context.session.scalars(
        select(CRMWorkItemOutcome).where(
            CRMWorkItemOutcome.tenant_id == tenant_id,
            CRMWorkItemOutcome.organization_unit_id == organization_unit_id,
            CRMWorkItemOutcome.id.in_(payload.outcome_ids),
        ).with_for_update()
    ))
    if len(outcomes) != len(payload.outcome_ids):
        raise HTTPException(status_code=422, detail="Every outcome must belong to the authorized organization")
    if any(outcome.outcome_code not in ("callback_requested", "no_contact") for outcome in outcomes):
        raise HTTPException(status_code=409, detail="Every selected outcome must request another follow-up")
    existing_task = await context.session.scalar(
        select(CRMWorkItem.id).where(
            CRMWorkItem.tenant_id == tenant_id,
            CRMWorkItem.source_outcome_id.in_(payload.outcome_ids),
        ).limit(1)
    )
    if existing_task is not None:
        raise HTTPException(status_code=409, detail="A selected outcome already has a follow-up task; refresh the queue")
    profiles = list(await context.session.scalars(
        select(CRMProfile).where(
            CRMProfile.tenant_id == tenant_id,
            CRMProfile.organization_unit_id == organization_unit_id,
            CRMProfile.id.in_([outcome.profile_id for outcome in outcomes]),
            CRMProfile.archived_at.is_(None),
            CRMProfile.merged_into_profile_id.is_(None),
        ).with_for_update()
    ))
    active_profile_ids = {profile.id for profile in profiles}
    if any(outcome.profile_id not in active_profile_ids for outcome in outcomes):
        raise HTTPException(status_code=409, detail="A selected customer is no longer active; refresh the queue")

    created = []
    for outcome in outcomes:
        reason = "callback requested" if outcome.outcome_code == "callback_requested" else "no contact"
        item = CRMWorkItem(
            id=uuid4(), tenant_id=tenant_id,
            organization_unit_id=organization_unit_id,
            profile_id=outcome.profile_id,
            opportunity_id=None, campaign_id=None,
            assigned_membership_id=payload.assigned_membership_id,
            created_by_membership_id=context.access.membership_id,
            title=f"Lifecycle follow-up: {reason}",
            description=f"Created from recorded outcome {outcome.id}; review the outcome before contacting the customer.",
            due_at=payload.due_at, priority=payload.priority,
            status="open", completed_at=None,
            source_outcome_id=outcome.id,
        )
        context.session.add(item)
        await context.session.flush()
        _audit(context, item, "crm_work_item.created", None, _snapshot(item))
        context.session.add(AuditEvent(
            tenant_id=tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="crm_work_item.created_from_outcome",
            target_type="crm_work_item_outcome",
            target_key=str(outcome.id),
            organization_unit_id=organization_unit_id,
            before_state=None,
            after_state={"work_item_id": str(item.id), "outcome_code": outcome.outcome_code},
            correlation_id=None,
        ))
        created.append(WorkItemRead.model_validate(item))
    await context.session.flush()
    return {"created_count": len(created), "items": created}


@router.get(
    "/lifecycle-follow-up-queue",
    response_model=dict,
    operation_id="listCRMLifecycleFollowUpActionQueue",
)
async def list_lifecycle_follow_up_action_queue(
    organization_unit_id: UUID,
    outcome_code: Literal["callback_requested", "no_contact"] | None = None,
    channel: ActivityChannel | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_created: bool = False,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    """List follow-up outcomes, optionally including the task created from each outcome."""
    tenant_id = context.access.tenant_id
    await _require_permission(context, "crm.work_item:view", organization_unit_id)
    follow_up_task = aliased(CRMWorkItem)
    latest_task_outcome = aliased(CRMWorkItemOutcome)
    latest_task_outcome_code = (
        select(latest_task_outcome.outcome_code)
        .where(
            latest_task_outcome.tenant_id == tenant_id,
            latest_task_outcome.work_item_id == follow_up_task.id,
        )
        .order_by(latest_task_outcome.occurred_at.desc(), latest_task_outcome.id.desc())
        .limit(1)
        .correlate(follow_up_task)
        .scalar_subquery()
    )
    latest_task_outcome_id = (
        select(latest_task_outcome.id)
        .where(
            latest_task_outcome.tenant_id == tenant_id,
            latest_task_outcome.work_item_id == follow_up_task.id,
        )
        .order_by(latest_task_outcome.occurred_at.desc(), latest_task_outcome.id.desc())
        .limit(1)
        .correlate(follow_up_task)
        .scalar_subquery()
    )
    follow_up_next_task = aliased(CRMWorkItem)
    latest_task_outcome_at = (
        select(latest_task_outcome.occurred_at)
        .where(
            latest_task_outcome.tenant_id == tenant_id,
            latest_task_outcome.work_item_id == follow_up_task.id,
        )
        .order_by(latest_task_outcome.occurred_at.desc(), latest_task_outcome.id.desc())
        .limit(1)
        .correlate(follow_up_task)
        .scalar_subquery()
    )
    has_follow_up_task = select(follow_up_task.id).where(
        follow_up_task.tenant_id == tenant_id,
        follow_up_task.organization_unit_id == organization_unit_id,
        follow_up_task.source_outcome_id == CRMWorkItemOutcome.id,
    ).correlate(CRMWorkItemOutcome).exists()
    stmt = (
        select(
            CRMWorkItemOutcome.id.label("outcome_id"),
            CRMWorkItemOutcome.profile_id,
            CRMWorkItemOutcome.work_item_id.label("source_work_item_id"),
            CRMWorkItemOutcome.outcome_code,
            CRMWorkItemOutcome.channel,
            CRMWorkItemOutcome.notes,
            CRMWorkItemOutcome.occurred_at,
            CRMWorkItemOutcome.recorded_by_membership_id,
            CRMWorkItem.title.label("source_work_item_title"),
            CRMWorkItem.status.label("source_work_item_status"),
            CRMProfile.display_name.label("customer_name"),
            follow_up_task.id.label("follow_up_task_id"),
            follow_up_task.status.label("follow_up_task_status"),
            follow_up_task.assigned_membership_id.label("follow_up_assigned_membership_id"),
            follow_up_task.due_at.label("follow_up_due_at"),
            follow_up_task.priority.label("follow_up_priority"),
            latest_task_outcome_code.label("follow_up_latest_outcome_code"),
            latest_task_outcome_at.label("follow_up_latest_outcome_at"),
            follow_up_next_task.id.label("follow_up_next_task_id"),
            follow_up_next_task.status.label("follow_up_next_task_status"),
            follow_up_next_task.assigned_membership_id.label("follow_up_next_task_assigned_membership_id"),
            follow_up_next_task.due_at.label("follow_up_next_task_due_at"),
        )
        .join(
            CRMWorkItem,
            (CRMWorkItem.tenant_id == CRMWorkItemOutcome.tenant_id)
            & (CRMWorkItem.id == CRMWorkItemOutcome.work_item_id),
        )
        .outerjoin(
            follow_up_task,
            (follow_up_task.tenant_id == CRMWorkItemOutcome.tenant_id)
            & (follow_up_task.source_outcome_id == CRMWorkItemOutcome.id)
            & (follow_up_task.organization_unit_id == organization_unit_id),
        )
        .outerjoin(
            follow_up_next_task,
            (follow_up_next_task.tenant_id == tenant_id)
            & (follow_up_next_task.organization_unit_id == organization_unit_id)
            & (follow_up_next_task.source_outcome_id == latest_task_outcome_id),
        )
        .join(
            CRMProfile,
            (CRMProfile.tenant_id == CRMWorkItemOutcome.tenant_id)
            & (CRMProfile.id == CRMWorkItemOutcome.profile_id)
            & (CRMProfile.organization_unit_id == CRMWorkItemOutcome.organization_unit_id),
        )
        .where(
            CRMWorkItemOutcome.tenant_id == tenant_id,
            CRMWorkItemOutcome.organization_unit_id == organization_unit_id,
            CRMWorkItem.organization_unit_id == organization_unit_id,
            CRMProfile.archived_at.is_(None),
            CRMProfile.merged_into_profile_id.is_(None),
            CRMWorkItemOutcome.outcome_code.in_(("callback_requested", "no_contact")),
            *([] if include_created else [~has_follow_up_task]),
        )
    )
    if outcome_code is not None:
        stmt = stmt.where(CRMWorkItemOutcome.outcome_code == outcome_code)
    if channel is not None:
        stmt = stmt.where(CRMWorkItemOutcome.channel == channel)
    total = await context.session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ) or 0
    rows = (await context.session.execute(
        stmt.order_by(CRMWorkItemOutcome.occurred_at.desc(), CRMWorkItemOutcome.id)
        .limit(limit).offset(offset)
    )).all()
    items = [
        {
            "outcome_id": str(row.outcome_id),
            "profile_id": str(row.profile_id),
            "customer_name": row.customer_name,
            "source_work_item_id": str(row.source_work_item_id),
            "source_work_item_title": row.source_work_item_title,
            "source_work_item_status": row.source_work_item_status,
            "outcome_code": row.outcome_code,
            "channel": row.channel,
            "notes": row.notes,
            "occurred_at": row.occurred_at.isoformat(),
            "recorded_by_membership_id": str(row.recorded_by_membership_id),
            "follow_up_task_id": str(row.follow_up_task_id) if row.follow_up_task_id else None,
            "follow_up_task_status": row.follow_up_task_status,
            "follow_up_assigned_membership_id": (str(row.follow_up_assigned_membership_id) if row.follow_up_assigned_membership_id else None),
            "follow_up_due_at": row.follow_up_due_at.isoformat() if row.follow_up_due_at else None,
            "follow_up_priority": row.follow_up_priority,
            "follow_up_latest_outcome_code": row.follow_up_latest_outcome_code,
            "follow_up_latest_outcome_at": (
                row.follow_up_latest_outcome_at.isoformat()
                if row.follow_up_latest_outcome_at else None
            ),
            "follow_up_next_task_id": str(row.follow_up_next_task_id) if row.follow_up_next_task_id else None,
            "follow_up_next_task_status": row.follow_up_next_task_status,
            "follow_up_next_task_assigned_membership_id": (
                str(row.follow_up_next_task_assigned_membership_id)
                if row.follow_up_next_task_assigned_membership_id else None
            ),
            "follow_up_next_task_due_at": (
                row.follow_up_next_task_due_at.isoformat()
                if row.follow_up_next_task_due_at else None
            ),
        }
        for row in rows
    ]
    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.lifecycle_follow_up_queue_viewed",
        target_type="crm_work_item_collection",
        target_key=str(organization_unit_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "outcome_code": outcome_code,
            "channel": channel,
            "limit": limit,
            "offset": offset,
            "include_created": include_created,
            "total": total,
            "returned_count": len(items),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return {"organization_unit_id": str(organization_unit_id), "total": total, "items": items}

@router.get("/{item_id}", response_model=WorkItemRead,
            operation_id="getCRMWorkItem")
async def get_work_item(
    item_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> WorkItemRead:
    item = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.id == item_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="CRM work item not found")
    await _require_permission(context, "crm.work_item:view", item.organization_unit_id)
    _audit(context, item, "crm_work_item.viewed", None, _snapshot(item))
    await context.session.flush()
    return WorkItemRead.model_validate(item)


async def _require_lifecycle_review_work_item(
    context: TenantSessionContext, item: CRMWorkItem
) -> None:
    if item.profile_id is None:
        raise HTTPException(status_code=422, detail="Lifecycle follow-up outcomes require a linked customer")
    if item.source_outcome_id is not None:
        return
    is_lifecycle_item = await context.session.scalar(
        select(AuditEvent.event_id).where(
            AuditEvent.tenant_id == context.access.tenant_id,
            AuditEvent.target_type == "crm_work_item",
            AuditEvent.target_key == str(item.id),
            AuditEvent.action_key == "crm_work_item.created_from_lifecycle_review",
        ).limit(1)
    )
    if is_lifecycle_item is None:
        raise HTTPException(status_code=404, detail="Lifecycle review work item not found")


@router.post(
    "/{item_id}/outcomes",
    response_model=WorkItemOutcomeRead,
    status_code=201,
    operation_id="recordCRMLifecycleFollowUpOutcome",
)
async def record_lifecycle_follow_up_outcome(
    item_id: UUID,
    payload: WorkItemOutcomeCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> WorkItemOutcomeRead:
    item = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.id == item_id,
        ).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="CRM work item not found")
    await _require_permission(context, "crm.work_item:record_outcome", item.organization_unit_id)
    await _require_lifecycle_review_work_item(context, item)
    if item.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled follow-up work items cannot record outcomes")

    existing = await context.session.scalar(
        select(CRMWorkItemOutcome).where(
            CRMWorkItemOutcome.tenant_id == context.access.tenant_id,
            CRMWorkItemOutcome.request_id == payload.request_id,
        )
    )
    if existing is not None:
        matches = (
            existing.work_item_id == item.id
            and existing.outcome_code == payload.outcome_code
            and existing.channel == payload.channel
            and existing.notes == payload.notes
            and (payload.occurred_at is None or existing.occurred_at == payload.occurred_at)
        )
        if not matches:
            raise HTTPException(status_code=409, detail="Outcome request ID was already used for different data")
        return WorkItemOutcomeRead.model_validate(existing)

    outcome = CRMWorkItemOutcome(
        id=uuid4(),
        request_id=payload.request_id,
        tenant_id=context.access.tenant_id,
        organization_unit_id=item.organization_unit_id,
        work_item_id=item.id,
        profile_id=item.profile_id,
        recorded_by_membership_id=context.access.membership_id,
        outcome_code=payload.outcome_code,
        channel=payload.channel,
        notes=payload.notes,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    context.session.add(outcome)
    await context.session.flush()
    _audit(
        context,
        item,
        "crm_work_item.outcome_recorded",
        None,
        {
            "outcome_id": str(outcome.id),
            "request_id": str(outcome.request_id),
            "outcome_code": outcome.outcome_code,
            "channel": outcome.channel,
            "occurred_at": outcome.occurred_at.isoformat(),
            "notes_present": outcome.notes is not None,
        },
    )
    await context.session.flush()
    return WorkItemOutcomeRead.model_validate(outcome)


@router.get(
    "/{item_id}/outcomes",
    response_model=list[WorkItemOutcomeRead],
    operation_id="listCRMLifecycleFollowUpOutcomes",
)
async def list_lifecycle_follow_up_outcomes(
    item_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[WorkItemOutcomeRead]:
    item = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.id == item_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="CRM work item not found")
    await _require_permission(context, "crm.work_item:view", item.organization_unit_id)
    await _require_lifecycle_review_work_item(context, item)
    outcomes = (await context.session.scalars(
        select(CRMWorkItemOutcome).where(
            CRMWorkItemOutcome.tenant_id == context.access.tenant_id,
            CRMWorkItemOutcome.work_item_id == item.id,
        ).order_by(CRMWorkItemOutcome.occurred_at.desc(), CRMWorkItemOutcome.created_at.desc()).limit(limit)
    )).all()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.outcomes_listed",
        target_type="crm_work_item",
        target_key=str(item.id),
        organization_unit_id=item.organization_unit_id,
        before_state=None,
        after_state={"result_count": len(outcomes)},
        correlation_id=None,
    ))
    await context.session.flush()
    return [WorkItemOutcomeRead.model_validate(outcome) for outcome in outcomes]


@router.patch("/{item_id}", response_model=WorkItemRead,
              operation_id="updateCRMWorkItem")
async def update_work_item(
    item_id: UUID,
    payload: WorkItemUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> WorkItemRead:
    item = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.id == item_id,
        ).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="CRM work item not found")
    await _require_permission(context, "crm.work_item:update", item.organization_unit_id)
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Completed or cancelled work items cannot be changed")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field must be provided")
    before = _snapshot(item)
    proposed = {
        key: changes.get(key, getattr(item, key))
        for key in ("profile_id", "opportunity_id", "campaign_id")
    }
    await _validate_context(
        context, organization_unit_id=item.organization_unit_id, **proposed
    )
    if "assigned_membership_id" in changes:
        await _validate_assignee(context, changes["assigned_membership_id"])
    next_status = changes.get("status", item.status)
    allowed = {
        "open": {"open", "in_progress", "completed", "cancelled"},
        "in_progress": {"in_progress", "completed", "cancelled"},
    }
    if next_status not in allowed[item.status]:
        raise HTTPException(status_code=409, detail="Invalid work item status transition")
    for key, value in changes.items():
        if key != "status":
            setattr(item, key, value)
    item.status = next_status
    item.completed_at = datetime.now(timezone.utc) if next_status == "completed" else None
    item.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(context, item, "crm_work_item.updated", before, _snapshot(item))
    await context.session.flush()
    return WorkItemRead.model_validate(item)


class SalesReviewWorkItemBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    opportunity_ids: list[UUID] = Field(min_length=1, max_length=50)
    assigned_membership_id: UUID | None = None
    title_prefix: str = Field(default="Sales follow-up", min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None
    priority: WorkItemPriority = "normal"

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @field_validator("title_prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title_prefix must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_batch_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


@router.post(
    "/from-sales-review",
    response_model=dict,
    status_code=201,
    operation_id="createCRMWorkItemsFromSalesReview",
)
async def create_work_items_from_sales_review(
    payload: SalesReviewWorkItemBatch,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if len(set(payload.opportunity_ids)) != len(payload.opportunity_ids):
        raise HTTPException(status_code=422, detail="Opportunity IDs must be unique")
    target = await context.session.scalar(select(CRMSalesTarget).where(
        CRMSalesTarget.tenant_id == context.access.tenant_id,
        CRMSalesTarget.id == payload.target_id,
    ))
    if target is None:
        raise HTTPException(status_code=404, detail="Sales target not found")
    await _require_permission(context, "crm.sales_target:view", target.organization_unit_id)
    await _require_permission(context, "crm.opportunity:view", target.organization_unit_id)
    await _require_permission(context, "crm.work_item:create", target.organization_unit_id)
    await _validate_assignee(context, payload.assigned_membership_id)
    pipeline = await context.session.scalar(select(CRMPipeline).where(
        CRMPipeline.tenant_id == target.tenant_id,
        CRMPipeline.id == target.pipeline_id,
        CRMPipeline.entity_kind == "opportunity",
    ))
    if pipeline is None:
        raise HTTPException(status_code=409, detail="Sales target pipeline is unavailable")
    stage_outcomes = {
        stage.get("key"): stage.get("outcome_key", "open")
        for stage in pipeline.stages
        if isinstance(stage, dict) and isinstance(stage.get("key"), str)
    }
    opportunities = list(await context.session.scalars(select(CRMOpportunity).where(
        CRMOpportunity.tenant_id == target.tenant_id,
        CRMOpportunity.organization_unit_id == target.organization_unit_id,
        CRMOpportunity.pipeline_id == target.pipeline_id,
        CRMOpportunity.id.in_(payload.opportunity_ids),
    ).with_for_update()))
    opportunity_by_id = {item.id: item for item in opportunities}
    if len(opportunity_by_id) != len(payload.opportunity_ids):
        raise HTTPException(status_code=422, detail="Every opportunity must belong to this target's organization and pipeline")
    for opportunity in opportunities:
        stage_outcome = stage_outcomes.get(opportunity.stage_key, "open")
        in_target_period = (
            opportunity.expected_close_date is None
            or target.period_start <= opportunity.expected_close_date <= target.period_end
        )
        matching_currency = opportunity.currency in (target.currency, None)
        if stage_outcome != "open" or not in_target_period or not matching_currency:
            raise HTTPException(
                status_code=422,
                detail="Only open opportunities in this target period and currency can be selected",
            )
    created = []
    for opportunity_id in payload.opportunity_ids:
        opportunity = opportunity_by_id[opportunity_id]
        title = f"{payload.title_prefix}: {opportunity.name}"[:200]
        item = CRMWorkItem(
            id=uuid4(),
            tenant_id=target.tenant_id,
            organization_unit_id=target.organization_unit_id,
            profile_id=opportunity.profile_id,
            opportunity_id=opportunity.id,
            campaign_id=None,
            assigned_membership_id=payload.assigned_membership_id,
            created_by_membership_id=context.access.membership_id,
            title=title,
            description=payload.description,
            due_at=payload.due_at,
            priority=payload.priority,
            status="open",
            completed_at=None,
        )
        context.session.add(item)
        await context.session.flush()
        _audit(
            context,
            item,
            "crm_work_item.created_from_sales_review",
            None,
            {**_snapshot(item), "source_sales_target_id": str(target.id)},
        )
        created.append(WorkItemRead.model_validate(item))
    await context.session.flush()
    return {"created_count": len(created), "items": created}


class LifecycleReviewWorkItemBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    profile_ids: list[UUID] = Field(min_length=1, max_length=50)
    inactive_for_days: int = Field(ge=1, le=365)
    lifecycle_stage: str | None = Field(default=None, min_length=1, max_length=80)
    profile_kind: str | None = Field(default=None, min_length=1, max_length=40)
    assigned_membership_id: UUID | None = None
    title_prefix: str = Field(default="Lifecycle follow-up", min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1500)
    due_at: datetime | None = None
    priority: WorkItemPriority = "normal"

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @field_validator("title_prefix")
    @classmethod
    def normalize_lifecycle_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title_prefix must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_lifecycle_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


@router.post(
    "/from-lifecycle-review",
    response_model=dict,
    status_code=201,
    operation_id="createCRMWorkItemsFromLifecycleReview",
)
async def create_work_items_from_lifecycle_review(
    payload: LifecycleReviewWorkItemBatch,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if len(set(payload.profile_ids)) != len(payload.profile_ids):
        raise HTTPException(status_code=422, detail="Profile IDs must be unique")
    await _require_permission(context, "crm.profile:view", payload.organization_unit_id)
    await _require_permission(context, "crm.work_item:create", payload.organization_unit_id)
    await _validate_assignee(context, payload.assigned_membership_id)

    profiles = list(await context.session.scalars(
        select(CRMProfile).where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.organization_unit_id == payload.organization_unit_id,
            CRMProfile.id.in_(payload.profile_ids),
            CRMProfile.archived_at.is_(None),
            CRMProfile.merged_into_profile_id.is_(None),
        ).with_for_update()
    ))
    profile_by_id = {profile.id: profile for profile in profiles}
    if len(profile_by_id) != len(payload.profile_ids):
        raise HTTPException(
            status_code=422,
            detail="Every selected profile must be active and in the authorized organization",
        )
    for profile in profiles:
        if payload.lifecycle_stage is not None and profile.lifecycle_stage != payload.lifecycle_stage.strip():
            raise HTTPException(status_code=409, detail="A selected profile changed lifecycle stage; refresh the review queue")
        if payload.profile_kind is not None and profile.profile_kind != payload.profile_kind.strip():
            raise HTTPException(status_code=409, detail="A selected profile changed profile kind; refresh the review queue")

    now = datetime.now(timezone.utc)
    inactivity_boundary = now - timedelta(days=payload.inactive_for_days)
    activity_rows = (await context.session.execute(
        select(
            CRMCustomerActivity.profile_id,
            func.max(CRMCustomerActivity.occurred_at).label("latest_activity_at"),
            func.count(CRMCustomerActivity.id).label("activity_count"),
        ).where(
            CRMCustomerActivity.tenant_id == context.access.tenant_id,
            CRMCustomerActivity.profile_id.in_(payload.profile_ids),
            CRMCustomerActivity.occurred_at <= now,
        ).group_by(CRMCustomerActivity.profile_id)
    )).all()
    activity_by_profile = {row.profile_id: row for row in activity_rows}
    stale_profiles = [
        profile_id
        for profile_id, row in activity_by_profile.items()
        if row.latest_activity_at is not None and row.latest_activity_at >= inactivity_boundary
    ]
    if stale_profiles:
        raise HTTPException(
            status_code=409,
            detail="At least one selected profile no longer matches the inactivity rule; refresh the review queue",
        )

    created = []
    for profile_id in payload.profile_ids:
        profile = profile_by_id[profile_id]
        activity = activity_by_profile.get(profile_id)
        latest_activity = activity.latest_activity_at if activity is not None else None
        evidence = (
            f"Selected inactivity rule: {payload.inactive_for_days} days. "
            + (
                f"Latest linked CRM activity: {latest_activity.isoformat()}; "
                f"recorded activity count: {int(activity.activity_count)}."
                if latest_activity is not None
                else "No linked CRM activity is recorded. This does not prove no interaction occurred."
            )
        )
        description = "\n\n".join(
            part for part in (payload.description, evidence) if part
        )[:2000]
        item = CRMWorkItem(
            id=uuid4(),
            tenant_id=context.access.tenant_id,
            organization_unit_id=payload.organization_unit_id,
            profile_id=profile.id,
            opportunity_id=None,
            campaign_id=None,
            assigned_membership_id=payload.assigned_membership_id,
            created_by_membership_id=context.access.membership_id,
            title=f"{payload.title_prefix}: {profile.display_name}"[:200],
            description=description,
            due_at=payload.due_at,
            priority=payload.priority,
            status="open",
            completed_at=None,
        )
        context.session.add(item)
        await context.session.flush()
        _audit(
            context,
            item,
            "crm_work_item.created_from_lifecycle_review",
            None,
            {
                **_snapshot(item),
                "source": "customer_lifecycle_follow_up_review",
                "inactive_for_days": payload.inactive_for_days,
                "latest_recorded_activity_at": latest_activity.isoformat() if latest_activity else None,
                "recorded_activity_count": int(activity.activity_count) if activity else 0,
            },
        )
        created.append(WorkItemRead.model_validate(item))
    await context.session.flush()
    return {"created_count": len(created), "items": created}
