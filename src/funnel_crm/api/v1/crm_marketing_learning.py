"""Manager-owned marketing learning cycles built on existing campaign target evaluations."""

from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_campaign_targets import evaluate_plan_metrics
from funnel_crm.api.v1.crm_work_items import WorkItemRead
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignExperiment,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMMarketingLearningReview,
    CRMWorkItem,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/marketing-learning/reviews", tags=["CRM marketing learning"])


class LearningReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    target_plan_id: UUID
    experiment_id: UUID | None = None
    assessment: str = Field(min_length=1, max_length=1200)
    corrective_action: str = Field(min_length=1, max_length=1200)

    @field_validator("assessment", "corrective_action")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must contain a non-whitespace character")
        return value


class LearningReviewEvaluationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow_up_target_plan_id: UUID
    follow_up_effectiveness: str = Field(min_length=1, max_length=1200)
    lesson_learned: str = Field(min_length=1, max_length=1200)
    status: Literal["evaluated"] = "evaluated"

    @field_validator("follow_up_effectiveness", "lesson_learned")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must contain a non-whitespace character")
        return value


class LearningReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    campaign_id: UUID
    target_plan_id: UUID
    experiment_id: UUID | None
    follow_up_target_plan_id: UUID | None
    assessment: str
    corrective_action: str
    follow_up_effectiveness: str | None
    lesson_learned: str | None
    status: Literal["planned", "evaluated"]
    created_at: datetime
    updated_at: datetime


class TargetEvaluationSnapshot(BaseModel):
    target_plan_id: UUID
    period_start: date
    period_end: date
    metrics: dict


class LearningReviewDetail(BaseModel):
    review: LearningReviewRead
    baseline: TargetEvaluationSnapshot
    follow_up: TargetEvaluationSnapshot | None


class LearningPortfolioItem(BaseModel):
    review: LearningReviewRead
    campaign_name: str
    baseline_period_start: date
    baseline_period_end: date
    follow_up_period_start: date | None
    follow_up_period_end: date | None
    learning_state: Literal["awaiting_follow_up", "follow_up_evaluated"]
    work_item: WorkItemRead | None = None


class LearningPortfolioReport(BaseModel):
    generated_at: datetime
    period_start: date | None
    period_end: date | None
    status_filter: Literal["planned", "evaluated"] | None
    total_count: int
    planned_count: int
    evaluated_count: int
    work_item_counts: dict[str, int] | None
    has_more: bool
    items: list[LearningPortfolioItem]
    basis: str


class LearningReviewWorkItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_membership_id: UUID | None = None
    due_at: datetime | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value


class LearningReviewWorkItemResult(BaseModel):
    work_item: WorkItemRead
    created: bool


async def _campaign(
    context: TenantSessionContext, campaign_id: UUID, permission: str
) -> CRMMarketingCampaign:
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="CRM campaign not found")
    if not await has_crm_permission(
        context, permission_key=permission,
        organization_unit_id=campaign.organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="Marketing learning review is not authorized for this organization scope")
    return campaign


async def _target_plan(
    context: TenantSessionContext,
    *,
    campaign: CRMMarketingCampaign,
    target_plan_id: UUID,
) -> CRMMarketingCampaignTargetPlan:
    plan = await context.session.scalar(
        select(CRMMarketingCampaignTargetPlan).where(
            CRMMarketingCampaignTargetPlan.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignTargetPlan.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignTargetPlan.campaign_id == campaign.id,
            CRMMarketingCampaignTargetPlan.id == target_plan_id,
        )
    )
    if plan is None:
        raise HTTPException(status_code=422, detail="Target plan must belong to the selected campaign and organization")
    return plan


async def _snapshot(
    context: TenantSessionContext,
    plan: CRMMarketingCampaignTargetPlan,
) -> TargetEvaluationSnapshot:
    rows = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id == plan.organization_unit_id,
            CRMMarketingCampaignMeasurement.campaign_id == plan.campaign_id,
            CRMMarketingCampaignMeasurement.measured_on >= plan.period_start,
            CRMMarketingCampaignMeasurement.measured_on <= plan.period_end,
        ).order_by(CRMMarketingCampaignMeasurement.measured_on)
    )).all()
    return TargetEvaluationSnapshot(
        target_plan_id=plan.id,
        period_start=plan.period_start,
        period_end=plan.period_end,
        metrics=evaluate_plan_metrics(plan, rows),
    )


async def _detail(
    context: TenantSessionContext,
    review: CRMMarketingLearningReview,
) -> LearningReviewDetail:
    baseline_plan = await _target_plan(
        context, campaign=await _campaign(context, review.campaign_id, "crm.campaign:view"),
        target_plan_id=review.target_plan_id,
    )
    follow_up = None
    if review.follow_up_target_plan_id is not None:
        follow_up_plan = await _target_plan(
            context, campaign=await _campaign(context, review.campaign_id, "crm.campaign:view"),
            target_plan_id=review.follow_up_target_plan_id,
        )
        follow_up = await _snapshot(context, follow_up_plan)
    return LearningReviewDetail(
        review=LearningReviewRead.model_validate(review),
        baseline=await _snapshot(context, baseline_plan),
        follow_up=follow_up,
    )


def _audit(
    context: TenantSessionContext,
    review: CRMMarketingLearningReview,
    action: str,
    *,
    before: dict | None,
    after: dict,
) -> None:
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key=action,
        target_type="crm_marketing_learning_review",
        target_key=str(review.id),
        organization_unit_id=review.organization_unit_id,
        before_state=before,
        after_state=after,
        correlation_id=None,
    ))


@router.post("", response_model=LearningReviewRead, status_code=201,
             operation_id="createCRMMarketingLearningReview")
async def create_learning_review(
    payload: LearningReviewCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> LearningReviewRead:
    campaign = await _campaign(context, payload.campaign_id, "crm.campaign:manage")
    await _target_plan(context, campaign=campaign, target_plan_id=payload.target_plan_id)
    if payload.experiment_id is not None:
        experiment = await context.session.scalar(
            select(CRMMarketingCampaignExperiment).where(
                CRMMarketingCampaignExperiment.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignExperiment.organization_unit_id == campaign.organization_unit_id,
                CRMMarketingCampaignExperiment.id == payload.experiment_id,
            )
        )
        if experiment is None:
            raise HTTPException(status_code=422, detail="Experiment must belong to the selected organization")

    review = CRMMarketingLearningReview(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=campaign.organization_unit_id, campaign_id=campaign.id,
        target_plan_id=payload.target_plan_id, experiment_id=payload.experiment_id,
        assessment=payload.assessment, corrective_action=payload.corrective_action,
        status="planned",
    )
    context.session.add(review)
    await context.session.flush()
    _audit(context, review, "crm_marketing_learning_review.created", before=None, after={
        "campaign_id": str(review.campaign_id), "target_plan_id": str(review.target_plan_id),
        "experiment_id": str(review.experiment_id) if review.experiment_id else None,
        "status": review.status,
    })
    await context.session.flush()
    return LearningReviewRead.model_validate(review)


@router.get("", response_model=list[LearningReviewRead],
            operation_id="listCRMMarketingLearningReviews")
async def list_learning_reviews(
    campaign_id: UUID | None = None,
    status: Literal["planned", "evaluated"] | None = Query(default=None),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[LearningReviewRead]:
    stmt = select(CRMMarketingLearningReview).where(
        CRMMarketingLearningReview.tenant_id == context.access.tenant_id
    )
    if campaign_id is not None:
        stmt = stmt.where(CRMMarketingLearningReview.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(CRMMarketingLearningReview.status == status)
    reviews = (await context.session.scalars(
        stmt.order_by(CRMMarketingLearningReview.updated_at.desc()).limit(200)
    )).all()
    visible = []
    for review in reviews:
        if await has_crm_permission(
            context, permission_key="crm.campaign:view",
            organization_unit_id=review.organization_unit_id,
        ):
            visible.append(LearningReviewRead.model_validate(review))
    return visible


@router.get("/portfolio", response_model=LearningPortfolioReport,
            operation_id="getCRMMarketingLearningPortfolio")
async def get_learning_portfolio(
    period_start: date | None = None,
    period_end: date | None = None,
    status: Literal["planned", "evaluated"] | None = Query(default=None),
    organization_unit_id: UUID | None = None,
    include_work_items: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> LearningPortfolioReport:
    if period_start is not None and period_end is not None and period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if period_start is not None and period_end is not None and (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Reports are limited to 366 calendar days")
    scopes = crm_scope_ids(
        context, permission_key="crm.campaign:view", cte_name="crm_learning_campaign_scope"
    )
    work_item_scopes = None
    if organization_unit_id is not None and not await has_crm_permission(
        context, permission_key="crm.campaign:view", organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Marketing learning portfolio is not authorized")
    if include_work_items:
        if organization_unit_id is not None and not await has_crm_permission(
            context, permission_key="crm.work_item:view", organization_unit_id=organization_unit_id
        ):
            raise HTTPException(status_code=403, detail="CRM work item portfolio is not authorized")
        work_item_scopes = crm_scope_ids(
            context, permission_key="crm.work_item:view", cte_name="crm_learning_work_item_scope"
        )

    follow_up_plan = aliased(CRMMarketingCampaignTargetPlan)
    review_filters = [
        CRMMarketingLearningReview.tenant_id == context.access.tenant_id,
        CRMMarketingLearningReview.organization_unit_id.in_(scopes),
    ]
    if organization_unit_id is not None:
        review_filters.append(CRMMarketingLearningReview.organization_unit_id == organization_unit_id)
    if work_item_scopes is not None:
        review_filters.append(CRMMarketingLearningReview.organization_unit_id.in_(work_item_scopes))
    if period_start is not None:
        review_filters.append(CRMMarketingCampaignTargetPlan.period_end >= period_start)
    if period_end is not None:
        review_filters.append(CRMMarketingCampaignTargetPlan.period_start <= period_end)
    filters = list(review_filters)
    if status is not None:
        filters.append(CRMMarketingLearningReview.status == status)
    base = (
        select(CRMMarketingLearningReview, CRMMarketingCampaign.name,
               CRMMarketingCampaignTargetPlan.period_start,
               CRMMarketingCampaignTargetPlan.period_end,
               follow_up_plan.period_start, follow_up_plan.period_end)
        .join(CRMMarketingCampaign,
              (CRMMarketingCampaign.tenant_id == CRMMarketingLearningReview.tenant_id)
              & (CRMMarketingCampaign.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
              & (CRMMarketingCampaign.id == CRMMarketingLearningReview.campaign_id))
        .join(CRMMarketingCampaignTargetPlan,
              (CRMMarketingCampaignTargetPlan.tenant_id == CRMMarketingLearningReview.tenant_id)
              & (CRMMarketingCampaignTargetPlan.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
              & (CRMMarketingCampaignTargetPlan.campaign_id == CRMMarketingLearningReview.campaign_id)
              & (CRMMarketingCampaignTargetPlan.id == CRMMarketingLearningReview.target_plan_id))
        .outerjoin(follow_up_plan,
              (follow_up_plan.tenant_id == CRMMarketingLearningReview.tenant_id)
              & (follow_up_plan.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
              & (follow_up_plan.campaign_id == CRMMarketingLearningReview.campaign_id)
              & (follow_up_plan.id == CRMMarketingLearningReview.follow_up_target_plan_id))
        .where(*filters)
    )
    if include_work_items:
        base = base.add_columns(CRMWorkItem).outerjoin(
            CRMWorkItem,
            (CRMWorkItem.tenant_id == CRMMarketingLearningReview.tenant_id)
            & (CRMWorkItem.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
            & (CRMWorkItem.campaign_id == CRMMarketingLearningReview.campaign_id)
            & (CRMWorkItem.source_learning_review_id == CRMMarketingLearningReview.id),
        )
    count_stmt = select(func.count(CRMMarketingLearningReview.id)).join(
        CRMMarketingCampaignTargetPlan,
        (CRMMarketingCampaignTargetPlan.tenant_id == CRMMarketingLearningReview.tenant_id)
        & (CRMMarketingCampaignTargetPlan.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
        & (CRMMarketingCampaignTargetPlan.campaign_id == CRMMarketingLearningReview.campaign_id)
        & (CRMMarketingCampaignTargetPlan.id == CRMMarketingLearningReview.target_plan_id),
    ).where(*filters)
    total = int(await context.session.scalar(count_stmt) or 0)
    status_counts = (await context.session.execute(
        select(CRMMarketingLearningReview.status, func.count(CRMMarketingLearningReview.id))
        .join(CRMMarketingCampaignTargetPlan,
              (CRMMarketingCampaignTargetPlan.tenant_id == CRMMarketingLearningReview.tenant_id)
              & (CRMMarketingCampaignTargetPlan.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
              & (CRMMarketingCampaignTargetPlan.campaign_id == CRMMarketingLearningReview.campaign_id)
              & (CRMMarketingCampaignTargetPlan.id == CRMMarketingLearningReview.target_plan_id))
        .where(*review_filters).group_by(CRMMarketingLearningReview.status)
    )).all()
    work_item_counts: dict[str, int] | None = None
    if include_work_items:
        task_status_rows = (await context.session.execute(
            select(CRMWorkItem.status, func.count(CRMWorkItem.id))
            .join(CRMMarketingLearningReview,
                  (CRMMarketingLearningReview.tenant_id == CRMWorkItem.tenant_id)
                  & (CRMMarketingLearningReview.organization_unit_id == CRMWorkItem.organization_unit_id)
                  & (CRMMarketingLearningReview.campaign_id == CRMWorkItem.campaign_id)
                  & (CRMMarketingLearningReview.id == CRMWorkItem.source_learning_review_id))
            .join(CRMMarketingCampaignTargetPlan,
                  (CRMMarketingCampaignTargetPlan.tenant_id == CRMMarketingLearningReview.tenant_id)
                  & (CRMMarketingCampaignTargetPlan.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
                  & (CRMMarketingCampaignTargetPlan.campaign_id == CRMMarketingLearningReview.campaign_id)
                  & (CRMMarketingCampaignTargetPlan.id == CRMMarketingLearningReview.target_plan_id))
            .where(*filters).group_by(CRMWorkItem.status)
        )).all()
        task_counts = {key: int(value) for key, value in task_status_rows}
        linked_count = sum(task_counts.values())
        overdue_count = int(await context.session.scalar(
            select(func.count(CRMWorkItem.id))
            .join(CRMMarketingLearningReview,
                  (CRMMarketingLearningReview.tenant_id == CRMWorkItem.tenant_id)
                  & (CRMMarketingLearningReview.organization_unit_id == CRMWorkItem.organization_unit_id)
                  & (CRMMarketingLearningReview.campaign_id == CRMWorkItem.campaign_id)
                  & (CRMMarketingLearningReview.id == CRMWorkItem.source_learning_review_id))
            .join(CRMMarketingCampaignTargetPlan,
                  (CRMMarketingCampaignTargetPlan.tenant_id == CRMMarketingLearningReview.tenant_id)
                  & (CRMMarketingCampaignTargetPlan.organization_unit_id == CRMMarketingLearningReview.organization_unit_id)
                  & (CRMMarketingCampaignTargetPlan.campaign_id == CRMMarketingLearningReview.campaign_id)
                  & (CRMMarketingCampaignTargetPlan.id == CRMMarketingLearningReview.target_plan_id))
            .where(*filters, CRMWorkItem.status.in_(("open", "in_progress")),
                   CRMWorkItem.due_at.is_not(None), CRMWorkItem.due_at < datetime.now(timezone.utc))
        ) or 0)
        work_item_counts = {
            "linked": linked_count,
            "without_work_item": max(total - linked_count, 0),
            "open": task_counts.get("open", 0),
            "in_progress": task_counts.get("in_progress", 0),
            "completed": task_counts.get("completed", 0),
            "cancelled": task_counts.get("cancelled", 0),
            "overdue": overdue_count,
        }
    rows = (await context.session.execute(
        base.order_by(CRMMarketingLearningReview.status, CRMMarketingLearningReview.updated_at.desc(),
                      CRMMarketingLearningReview.id)
        .limit(limit).offset(offset)
    )).all()
    items = [LearningPortfolioItem(
        review=LearningReviewRead.model_validate(row[0]),
        campaign_name=row[1],
        baseline_period_start=row[2],
        baseline_period_end=row[3],
        follow_up_period_start=row[4],
        follow_up_period_end=row[5],
        learning_state="follow_up_evaluated" if row[0].status == "evaluated" else "awaiting_follow_up",
        work_item=WorkItemRead.model_validate(row[6]) if include_work_items and row[6] is not None else None,
    ) for row in rows]
    counts = {key: int(value) for key, value in status_counts}
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_learning.portfolio_viewed",
        target_type="crm_marketing_learning_portfolio",
        target_key=str(organization_unit_id or context.access.tenant_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={"period_start": period_start.isoformat() if period_start else None,
                     "period_end": period_end.isoformat() if period_end else None,
                     "status": status, "include_work_items": include_work_items,
                     "total_count": total, "returned_count": len(items),
                     "offset": offset, "limit": limit},
        correlation_id=None,
    ))
    await context.session.flush()
    return LearningPortfolioReport(
        generated_at=datetime.now(timezone.utc), period_start=period_start,
        period_end=period_end, status_filter=status, total_count=total,
        planned_count=counts.get("planned", 0), evaluated_count=counts.get("evaluated", 0),
        work_item_counts=work_item_counts,
        has_more=offset + len(items) < total, items=items,
        basis=("Manager-authored assessments, corrective actions, and follow-up records linked to "
               "their baseline and follow-up campaign target periods; observed changes do not establish causality."),
    )


@router.get("/{review_id}", response_model=LearningReviewDetail,
            operation_id="getCRMMarketingLearningReview")
async def get_learning_review(
    review_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> LearningReviewDetail:
    review = await context.session.scalar(
        select(CRMMarketingLearningReview).where(
            CRMMarketingLearningReview.tenant_id == context.access.tenant_id,
            CRMMarketingLearningReview.id == review_id,
        )
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Marketing learning review not found")
    detail = await _detail(context, review)
    _audit(context, review, "crm_marketing_learning_review.viewed", before=None, after={
        "status": review.status, "baseline_target_plan_id": str(review.target_plan_id),
        "follow_up_target_plan_id": str(review.follow_up_target_plan_id)
        if review.follow_up_target_plan_id else None,
    })
    await context.session.flush()
    return detail


@router.post("/{review_id}/work-item", response_model=LearningReviewWorkItemResult,
             operation_id="createCRMMarketingLearningReviewWorkItem")
async def create_learning_review_work_item(
    review_id: UUID,
    payload: LearningReviewWorkItemRequest,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> LearningReviewWorkItemResult:
    review = await context.session.scalar(
        select(CRMMarketingLearningReview).where(
            CRMMarketingLearningReview.tenant_id == context.access.tenant_id,
            CRMMarketingLearningReview.id == review_id,
        ).with_for_update()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Marketing learning review not found")
    campaign = await _campaign(context, review.campaign_id, "crm.campaign:manage")
    await _target_plan(context, campaign=campaign, target_plan_id=review.target_plan_id)
    if not await has_crm_permission(
        context, permission_key="crm.work_item:create",
        organization_unit_id=campaign.organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="Creating a CRM work item is not authorized")
    existing = await context.session.scalar(
        select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == context.access.tenant_id,
            CRMWorkItem.source_learning_review_id == review.id,
        )
    )
    if existing is not None:
        return LearningReviewWorkItemResult(
            work_item=WorkItemRead.model_validate(existing), created=False
        )
    if payload.assigned_membership_id is not None:
        active_member = await context.session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.tenant_id == context.access.tenant_id,
                WorkspaceMembership.id == payload.assigned_membership_id,
                WorkspaceMembership.status == "active",
            )
        )
        if active_member is None:
            raise HTTPException(status_code=422, detail="Assignee must be an active member of this workspace")
    title = f"Marketing follow-up: {review.corrective_action}"
    if len(title) > 200:
        title = title[:197].rstrip() + "..."
    work_item = CRMWorkItem(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        organization_unit_id=campaign.organization_unit_id,
        profile_id=None,
        opportunity_id=None,
        campaign_id=campaign.id,
        assigned_membership_id=payload.assigned_membership_id,
        created_by_membership_id=context.access.membership_id,
        source_learning_review_id=review.id,
        title=title,
        description=(f"Corrective action: {review.corrective_action}\n"
                     f"Assessment: {review.assessment}")[:2000],
        due_at=payload.due_at,
        priority=payload.priority,
        status="open",
        completed_at=None,
    )
    context.session.add(work_item)
    await context.session.flush()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_work_item.created_from_marketing_learning_review",
        target_type="crm_work_item",
        target_key=str(work_item.id),
        organization_unit_id=campaign.organization_unit_id,
        before_state=None,
        after_state={"source_learning_review_id": str(review.id),
                     "campaign_id": str(campaign.id), "assigned_membership_id":
                     str(payload.assigned_membership_id) if payload.assigned_membership_id else None,
                     "priority": payload.priority},
        correlation_id=None,
    ))
    _audit(context, review, "crm_marketing_learning_review.work_item_created",
           before=None, after={"work_item_id": str(work_item.id)})
    await context.session.flush()
    return LearningReviewWorkItemResult(
        work_item=WorkItemRead.model_validate(work_item), created=True
    )


@router.patch("/{review_id}/evaluation", response_model=LearningReviewDetail,
              operation_id="evaluateCRMMarketingLearningReview")
async def evaluate_learning_review(
    review_id: UUID,
    payload: LearningReviewEvaluationUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> LearningReviewDetail:
    review = await context.session.scalar(
        select(CRMMarketingLearningReview).where(
            CRMMarketingLearningReview.tenant_id == context.access.tenant_id,
            CRMMarketingLearningReview.id == review_id,
        ).with_for_update()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Marketing learning review not found")
    campaign = await _campaign(context, review.campaign_id, "crm.campaign:manage")
    if review.status != "planned":
        raise HTTPException(status_code=409, detail="Only planned reviews can be evaluated")
    baseline_plan = await _target_plan(
        context, campaign=campaign, target_plan_id=review.target_plan_id
    )
    follow_up_plan = await _target_plan(
        context, campaign=campaign, target_plan_id=payload.follow_up_target_plan_id
    )
    if payload.follow_up_target_plan_id == review.target_plan_id:
        raise HTTPException(status_code=422, detail="Follow-up must use a different target plan")
    if follow_up_plan.period_start <= baseline_plan.period_end:
        raise HTTPException(status_code=422, detail="Follow-up target period must start after the reviewed period")
    follow_up_snapshot = await _snapshot(context, follow_up_plan)
    if not any(metric.actual is not None for metric in follow_up_snapshot.metrics.values()):
        raise HTTPException(status_code=422, detail="Follow-up cannot be evaluated without observed target data")
    before = {"status": review.status, "follow_up_target_plan_id": None}
    review.follow_up_target_plan_id = payload.follow_up_target_plan_id
    review.follow_up_effectiveness = payload.follow_up_effectiveness
    review.lesson_learned = payload.lesson_learned
    review.status = "evaluated"
    review.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(context, review, "crm_marketing_learning_review.evaluated", before=before, after={
        "status": review.status,
        "follow_up_target_plan_id": str(review.follow_up_target_plan_id),
        "follow_up_effectiveness": review.follow_up_effectiveness,
        "lesson_learned": review.lesson_learned,
    })
    await context.session.flush()
    return await _detail(context, review)
