"""Manager-owned marketing learning cycles built on existing campaign target evaluations."""

from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_campaign_targets import evaluate_plan_metrics
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignExperiment,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMMarketingLearningReview,
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
    await _target_plan(
        context, campaign=campaign, target_plan_id=payload.follow_up_target_plan_id
    )
    if payload.follow_up_target_plan_id == review.target_plan_id:
        raise HTTPException(status_code=422, detail="Follow-up must use a different target plan")
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
