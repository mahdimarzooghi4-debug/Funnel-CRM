"""Assignable, scoped work queue for customer and marketing follow-up."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import cast, func, select, String

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMMarketingCampaign,
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
