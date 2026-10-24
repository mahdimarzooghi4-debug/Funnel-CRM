"""Assignable, scoped work queue for customer and marketing follow-up."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMOpportunity,
    CRMPipeline,
    CRMSalesTarget,
    CRMProfile,
    CRMWorkItem,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/work-items", tags=["CRM work queue"])
WorkItemStatus = Literal["open", "in_progress", "completed", "cancelled"]
WorkItemPriority = Literal["low", "normal", "high", "urgent"]


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
    title: str
    description: str | None
    due_at: datetime | None
    priority: WorkItemPriority
    status: WorkItemStatus
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


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
